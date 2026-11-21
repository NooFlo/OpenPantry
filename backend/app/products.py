"""Barcode (EAN/GTIN) product lookups against Open Food Facts and its sister
projects (Open Beauty Facts, Open Products Facts), with a local SQLite cache.

Scanning a barcode that isn't mapped to an inventory item yet triggers an
online lookup; the result (name, brand, quantity, category labels) is cached
in the `barcode_cache` table so each barcode hits the API at most once
(negative results are re-checked after a TTL, to cover scanner misreads and
products added to the databases later).

Lookups are best-effort: without internet access an unknown barcode simply
reports as not found, it never blocks a scan.
"""

import difflib
import json
import re
from datetime import datetime, timezone

import httpx

from . import repo
from .db import get_db

SOURCES = (
    ("Open Food Facts", "https://world.openfoodfacts.org"),
    ("Open Beauty Facts", "https://world.openbeautyfacts.org"),
    ("Open Products Facts", "https://world.openproductsfacts.org"),
)
FIELDS = "product_name,generic_name,brands,quantity,categories,categories_tags,image_small_url"
TIMEOUT = 5.0
MISS_TTL_DAYS = 14


def _request(barcode: str) -> dict | None:
    """Query the OFF-family v2 API. German product entries carry their own
    (usually German) product names and category labels, which is exactly what
    the generic-catalog matching needs."""
    for source, host in SOURCES:
        try:
            response = httpx.get(
                f"{host}/api/v2/product/{barcode}.json",
                params={"fields": FIELDS},
                headers={"User-Agent": "OpenPantry home-pantry (github.com/NooFlo/OpenPantry)"},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError:
            continue
        if response.status_code != 200:
            continue
        try:
            data = response.json()
        except ValueError:
            continue
        if data.get("status") != 1:
            continue
        product = data.get("product") or {}
        name = (product.get("product_name") or product.get("generic_name") or "").strip()
        if not name:
            continue
        categories = [c.strip() for c in (product.get("categories") or []) if len(c.strip()) >= 3]
        tags = [
            t.split(":", 1)[1].replace("-", " ").strip()
            for t in (product.get("categories_tags") or [])
            if len(t) > 3
        ]
        return {
            "name": name,
            "brand": (product.get("brands") or "").split(",")[0].strip(),
            "quantity": (product.get("quantity") or "").strip(),
            "categories": categories + [t for t in tags if t not in categories],
            "image_url": product.get("image_small_url") or None,
            "source": source,
        }
    return None


def _from_row(row: dict) -> dict:
    return {
        "barcode": row["barcode"],
        "name": row["name"],
        "brand": row["brand"],
        "quantity": row["quantity"],
        "categories": _load_categories(row["categories_json"]),
        "image_url": row["image_url"],
        "source": row["source"],
    }


def _cache_get(barcode: str) -> tuple[dict | None, bool] | None:
    """Returns None without a cache row, else (product_or_None, fresh).

    Known products are cached forever; cached misses are fresh only within
    MISS_TTL_DAYS so products added to the databases later are picked up."""
    with get_db() as db:
        row = db.execute("SELECT * FROM barcode_cache WHERE barcode = ?", (barcode,)).fetchone()
    if not row:
        return None
    row = dict(row)
    fresh = row["status"] == "found"
    if not fresh:
        fetched = datetime.strptime(row["fetched_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        fresh = (datetime.now(timezone.utc) - fetched).days < MISS_TTL_DAYS
    return (None, fresh) if row["status"] == "miss" else (_from_row(row), True)


def _cache_put(barcode: str, product: dict | None) -> None:
    categories = (product or {}).get("categories") or []
    with get_db() as db:
        db.execute(
            "INSERT INTO barcode_cache (barcode, status, name, brand, quantity, image_url,"
            " categories_json, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(barcode) DO UPDATE SET status=excluded.status, name=excluded.name,"
            " brand=excluded.brand, quantity=excluded.quantity, image_url=excluded.image_url,"
            " categories_json=excluded.categories_json, source=excluded.source,"
            " fetched_at=datetime('now')",
            (
                barcode,
                "found" if product else "miss",
                (product or {}).get("name"),
                (product or {}).get("brand"),
                (product or {}).get("quantity"),
                (product or {}).get("image_url"),
                _dump_categories(categories),
                (product or {}).get("source"),
            ),
        )


def _dump_categories(categories: list) -> str:
    return json.dumps(categories, ensure_ascii=False)


def _load_categories(raw: str | None) -> list:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except ValueError:
        return []


def product_info(barcode: str, refresh: bool = False) -> dict | None:
    cached = _cache_get(barcode)
    if cached is not None and not refresh:
        product, fresh = cached
        # known products are served from cache forever, stale misses re-fetch
        if product is not None or fresh:
            return product
    product = _request(barcode)
    _cache_put(barcode, product)
    return product


def _similarity(candidate: str, item_name: str) -> float:
    """Score how well an OFF name/category label matches a catalog item.

    Containment beats fuzzy: German Eigenmarken compound words ("Jodsalz",
    "Meersalz", "Kokosmilch") contain the generic item verbatim — the rock5
    pipeline notes showed exactly this heuristic classifying real REWE lines
    with zero false positives, while whole-line fuzzy ratios scored 0/9.
    """
    cand = (candidate or "").strip().lower()
    iname = item_name.strip().lower()
    if not cand or not iname:
        return 0.0
    if cand == iname:
        return 2.0
    # German compounds put the generic item at the token head ("Jodsalz",
    # "Meersalz", "Kokosmilch") — accept prefix/suffix hits, but never an
    # arbitrary infix: "Cola" inside "chocoLAte" is a no ("Schokolade" is
    # its own catalog item).
    tokens = [t for t in re.split(r"[^a-z0-9äöüß]+", cand) if len(t) >= 3]
    if any(t == iname or t.startswith(iname) or t.endswith(iname) for t in tokens):
        return 1.6
    best_token = max(
        (difflib.SequenceMatcher(None, t, iname).ratio() for t in tokens),
        default=0.0,
    )
    whole = difflib.SequenceMatcher(None, cand, iname).ratio()
    return max(best_token, whole)


MIN_SUGGESTION_SCORE = 0.82


def suggest_items(product: dict, limit: int = 3) -> list[dict]:
    """Map an OFF product onto the pantry's generic catalog via its name and
    category labels. Category labels count slightly less than the product
    name itself; on ties the more specific (longer) item wins, so "Kokosmilch"
    outscores "Milch" for a coconut-milk product."""
    items = repo.list_items()
    scored = {}

    def consider(candidate: str, reason: str, scale: float) -> None:
        for item in items:
            iname = item["name"].strip().lower()
            if not iname:
                continue
            score = _similarity(candidate, iname) * scale
            current = scored.get(item["id"])
            if not current or score > current[0]:
                scored[item["id"]] = (score, reason, item)

    consider(product.get("name"), "name", 1.0)
    # OFF categories run broad → specific; the tail is the most specific
    for label in (product.get("categories") or [])[-5:]:
        consider(label, "category", 0.9)
    ranked = sorted(scored.values(), key=lambda e: (e[0], len(e[2]["name"])), reverse=True)
    return [
        {"id": item["id"], "name": item["name"], "reason": reason}
        for score, reason, item in ranked[:limit]
        if score >= MIN_SUGGESTION_SCORE
    ]


CATEGORY_HINTS = [
    ("Drinks", ("beverages", "getränke", "waters", "juices", "säfte", "safte",
                "sodas", "colas", "coffees", "kaffee", "teas", "beer", "bier",
                "wine", "wein")),
    ("Dairy", ("dairy", "milk", "milch", "cheese", "käse", "yogurt", "joghurt",
               "butter", "butters", "eggs", "eier", "cream", "sahne")),
    ("Meat", ("meat", "meats", "fleisch", "sausages", "wurst", "ham", "schinken",
              "poultry", "geflügel", "chicken", "hähnchen")),
    ("Produce", ("vegetables", "gemüse", "fruits", "obst", "produce", "tomatoes",
                 "tomaten", "potatoes", "kartoffeln", "onions", "zwiebeln",
                 "bananas", "bananen", "apples", "äpfel", "salads", "herbs",
                 "kräuter", "mushrooms", "pilze")),
    ("Household", ("household", "cleaning", "detergents", "spülmittel",
                   "waschmittel", "toilet", "hygiene", "cosmetics", "kosmetik")),
]


def guess_category(categories: list | None) -> str:
    """Best-effort Open Food Facts categories → OpenPantry category. Drinks
    first so `beverages` wins over stray milk-ish tags; default Pantry."""
    text = " ".join(categories or []).lower()
    for category, words in CATEGORY_HINTS:
        if any(word in text for word in words):
            return category
    return "Pantry"


def parse_quantity(quantity: str | None) -> tuple[float, str] | None:
    """'500 g' → (0.5, 'kg'), '1,5 l' → (1.5, 'l'), '2 Stück' → (2, 'pcs').

    Quantities are normalized to OpenPantry's kg/l/pcs unit spectrum, the
    natural package size for a new catalog item."""
    if not quantity:
        return None
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|stück|st)", quantity.strip().lower()
    )
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    unit = match.group(2)
    if unit == "g":
        return round(amount / 1000, 4), "kg"
    if unit == "ml":
        return round(amount / 1000, 4), "l"
    if unit == "kg":
        return amount, "kg"
    if unit == "l":
        return amount, "l"
    return amount, "pcs"


def discard_cached(barcode: str) -> bool:
    """Drop a cached product from the review queue (and any cached miss)."""
    with get_db() as db:
        cursor = db.execute("DELETE FROM barcode_cache WHERE barcode = ?", (barcode,))
    return cursor.rowcount > 0


def pending_barcodes() -> list[dict]:
    """Cached, identified products whose barcode isn't assigned to an item yet:
    the review queue for scans that came in before their mapping was confirmed."""
    with get_db() as db:
        rows = db.execute(
            "SELECT p.* FROM barcode_cache p"
            " LEFT JOIN item_barcodes b ON b.barcode = p.barcode"
            " WHERE p.status = 'found' AND b.item_id IS NULL"
            " ORDER BY p.fetched_at DESC"
        ).fetchall()
    pending = []
    for row in rows:
        entry = _from_row(dict(row))
        entry["suggestions"] = suggest_items(entry)
        pending.append(entry)
    return pending
