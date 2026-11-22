"""Import hygiene rules applied to every freshly parsed ingredient list.

Distilled from the import defects seen in practice:

- R1 raw artifacts: HTML entities leaking from source markup are
  decoded everywhere, markup-only rows drop out.
- R2 continuation fragments: a row starting with "And 1/2 cups..." or
  "oder 100 g ..." continues the row before it — its amount sums into
  that row instead of standing alone as a phantom ingredient.
- R3 same-item duplicates: rows naming the same food ("2 cups flour" +
  "1 cup flour") sum into the first row, keyed by the matched inventory
  item or the shared base name.

Amounts never get invented: a fragment without a number merges its raw
text only, and the shopping math treats result rows without amounts as
weak-signal "one of it", exactly as before.
"""

import html
import re
import sys

from . import extract

_FRAGMENT_RE = re.compile(
    r"^(?:and|oder|or)\s+\d|^[,;+]\s*\d|^/\s*\d|^und\s+\d|^\d\s*\d/\d", re.IGNORECASE
)

_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")

# markup: HTML tags and comment leftovers
_MARKUP_RE = re.compile(r"<[^>]*>")


def decode_entities(raw: str) -> str:
    """HTML entities out of a raw line, nbsp -> plain space."""
    if "&" in raw:
        raw = html.unescape(html.unescape(raw))
    return raw.replace("\xa0", " ")


def is_fragment(raw: str) -> bool:
    """True when a raw line only continues the ingredient row before it."""
    raw = raw.strip().lower()
    return bool(
        _FRAGMENT_RE.match(raw)
        or _MARKUP_RE.sub("", raw).strip() in ("", ",")
    )


def base_name(row: dict) -> str:
    """The food a row is about, reduced for dedupe comparisons."""
    name = (row.get("raw") or "").lower()
    return re.sub(r"[\d.,/()\s]+", " ", name).strip()


def _is_markup_only(raw: str) -> bool:
    return not _MARKUP_RE.sub("", raw).strip(" ,;.-–")


def sanitize(raw_rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Apply the rules; returns (rows, notes).

    A fragment with a plain number in the same unit as the row before it
    sums into that row's amount; anything else merges raw-text-only.
    Duplicate rows for the same food sum into the first row.
    """
    rows = [dict(r) for r in raw_rows]
    for row in rows:
        row["raw"] = decode_entities(row.get("raw") or "")
    # rows emptied by decoding disappear, and so do markup-only rows
    # (stray <br>, broken-entity leftovers)
    rows = [r for r in rows
            if (r.get("raw") or "").strip(" ,;.-–()")
            and _MARKUP_RE.sub("", r.get("raw") or "").strip(" ,;.-–()")]

    merged_rows: list[dict] = []
    notes: list[str] = []
    by_key: dict[str, dict] = {}
    for row in rows:
        key = row.get("item_id") or f"~{base_name(row)}"
        prev = merged_rows[-1] if merged_rows else None
        first = by_key.get(key)
        # a matched row also answers for its base name, so an unmatched
        # duplicate ("2 cups flour" again) finds it either way
        alt_key = f"~{base_name(row)}"
        if first is None and row.get("item_id"):
            first = by_key.get(alt_key)
        if first is not None:
            # duplicate: sum what both rows quantify, keep the first raw
            a, b = first.get("amount"), row.get("amount")
            if a is not None and b is not None:
                first["amount"] = a + b
            notes.append(f"merged duplicate {row.get('raw')!r} into {first.get('raw')!r}")
            continue
        if prev is not None and is_fragment(row["raw"]):
            # continuation of the row before: sum a plain number, and the
            # fragment's raw folds into the row's own text
            prev["raw"] = f"{prev['raw'].rstrip(' ,')}, {row['raw'].lstrip(', ')}"
            a, b = prev.get("amount"), row.get("amount")
            if a is not None and b is not None:
                prev["amount"] = a + b
            notes.append(f"merged fragment {row['raw']!r} into {prev['raw']!r}")
            continue
        if key:
            by_key[key] = row
        by_key.setdefault(alt_key, row)
        merged_rows.append(row)
    return merged_rows, notes
