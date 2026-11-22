import difflib
import json
import re
import uuid

from . import catalog
from . import naming
from .db import get_db


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_db() as db:
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def _barcodes_for(db, item_ids: list[str]) -> dict[str, list[str]]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" * len(item_ids))
    rows = db.execute(
        f"SELECT item_id, barcode FROM item_barcodes WHERE item_id IN ({placeholders})"
        " ORDER BY rowid",
        item_ids,
    ).fetchall()
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row["item_id"], []).append(row["barcode"])
    return out


def record_scan(kind: str, barcode: str | None, item: dict | None = None) -> None:
    """Durable scan history: every scanner action, succeeded or unknown.
    The in-memory event ring only pings the UI; this log survives restarts."""
    with get_db() as db:
        db.execute(
            "INSERT INTO scan_log (kind, barcode, item_id, item_name) VALUES (?, ?, ?, ?)",
            (kind, barcode, item["id"] if item else None, item["name"] if item else None),
        )


def recent_scans(limit: int = 60) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, at, kind, barcode, item_id, item_name FROM scan_log"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _derive_package_count(item: dict) -> int | None:
    """Qty-mode stock as whole packages (bottles, packs) — the number the
    user tracks, not the weight. Piece-tracked items count pieces directly;
    binary items don't count. Exact physical amounts stay in `quantity` for
    recipe deductions and the low-stock prognosis."""
    if item["tracking_mode"] == "binary":
        return None
    if item["unit"] == "pcs":
        return round(item["quantity"])
    return round(item["quantity"] / (item["package_size"] or 1))


def _attach_barcodes(items: list[dict]) -> list[dict]:
    """Every item gains `barcodes` (all of them) and `barcode` (the primary,
    first-assigned one — kept for the single-label UI and API compatibility),
    plus the derived whole-package `package_count`."""
    with get_db() as db:
        by_item = _barcodes_for(db, [i["id"] for i in items])
    for item in items:
        item["barcodes"] = by_item.get(item["id"], [])
        item["barcode"] = item["barcodes"][0] if item["barcodes"] else None
        item["package_count"] = _derive_package_count(item)
        concept = item.get("concept_id")
        if concept:
            meta = catalog.CONCEPTS.get(concept)
            item["concept_label"] = meta["de"] if meta else None
        item["auto_restock"] = bool(item.get("auto_restock", 0))
    return items


def list_items() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM items ORDER BY name").fetchall()
    return _attach_barcodes([dict(r) for r in rows])


def get_item(item_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return _attach_barcodes([dict(row)])[0] if row else None


def find_item_by_name(name: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM items WHERE lower(name) = lower(?)", (name,)).fetchone()
    return dict(row) if row else None


def find_item_by_barcode(barcode: str) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM items WHERE id ="
            " (SELECT item_id FROM item_barcodes WHERE barcode = ?)",
            (barcode,),
        ).fetchone()
    return _attach_barcodes([dict(row)])[0] if row else None


def add_item_barcode(item_id: str, barcode: str) -> dict | None:
    """Register another product barcode for an item (Aldi eggs, REWE eggs —
    same generic stock). Validation (format, other-item clashes) lives above
    this layer; INSERT OR IGNORE keeps duplicate calls idempotent."""
    with get_db() as db:
        if not db.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone():
            return None
        db.execute(
            "INSERT OR IGNORE INTO item_barcodes (item_id, barcode) VALUES (?, ?)",
            (item_id, barcode),
        )
        row = db.execute("SELECT barcode FROM item_barcodes WHERE item_id = ?"
                         " ORDER BY rowid LIMIT 1", (item_id,)).fetchone()
        db.execute("UPDATE items SET barcode = ? WHERE id = ?",
                   (row["barcode"] if row else None, item_id))
    return get_item(item_id)


def remove_item_barcode(item_id: str, barcode: str) -> dict | None:
    with get_db() as db:
        if not db.execute(
            "SELECT 1 FROM item_barcodes WHERE item_id = ? AND barcode = ?",
            (item_id, barcode),
        ).fetchone():
            return None
        db.execute("DELETE FROM item_barcodes WHERE item_id = ? AND barcode = ?",
                   (item_id, barcode))
        row = db.execute("SELECT barcode FROM item_barcodes WHERE item_id = ?"
                         " ORDER BY rowid LIMIT 1", (item_id,)).fetchone()
        db.execute("UPDATE items SET barcode = ? WHERE id = ?",
                   (row["barcode"] if row else None, item_id))
    return get_item(item_id)


def set_item_barcode(item_id: str, barcode: str) -> dict | None:
    """Legacy single-barcode setter kept for older API callers: adds the
    mapping without dropping existing ones (multi-barcode semantics)."""
    return add_item_barcode(item_id, barcode)


# ------------------------------------------------------------------ custom labels
# Drag-and-drop label designs in the LabelGenerator style: one per item
# (linked to exactly that item via the "Create custom label" checkbox) and
# one per scanner control code (bought / trash). Elements are stored as a
# JSON blob of absolutely positioned mm boxes.


def _label_out(row) -> dict:
    label = dict(row)
    try:
        elements = json.loads(label.pop("layout_json") or "[]")
    except (ValueError, TypeError):
        elements = []
    label["elements"] = elements if isinstance(elements, list) else []
    return label


def get_item_custom_label(item_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM custom_labels WHERE item_id = ?", (item_id,)).fetchone()
    return _label_out(row) if row else None


def save_item_custom_label(item_id: str, elements: list[dict],
                           width_mm: float = 50, tape: int = 24) -> dict | None:
    """Upsert the item's design. created_at survives edits (the list is
    sorted by most recently added); updated_at tracks design changes."""
    with get_db() as db:
        if not db.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone():
            return None
        existing = db.execute(
            "SELECT id FROM custom_labels WHERE item_id = ?", (item_id,)).fetchone()
        if existing:
            db.execute(
                "UPDATE custom_labels SET layout_json = ?, width_mm = ?, tape = ?,"
                " updated_at = datetime('now') WHERE item_id = ?",
                (json.dumps(elements), width_mm, tape, item_id),
            )
        else:
            db.execute(
                "INSERT INTO custom_labels (id, item_id, layout_json, width_mm, tape)"
                " VALUES (?, ?, ?, ?, ?)",
                (new_id(), item_id, json.dumps(elements), width_mm, tape),
            )
    return get_item_custom_label(item_id)


def delete_item_custom_label(item_id: str) -> bool:
    with get_db() as db:
        cursor = db.execute("DELETE FROM custom_labels WHERE item_id = ?", (item_id,))
        return cursor.rowcount > 0


def list_item_custom_labels() -> list[dict]:
    """Items with a custom label, most recently added first."""
    with get_db() as db:
        rows = db.execute(
            "SELECT item_id, created_at, updated_at FROM custom_labels"
            " WHERE item_id IS NOT NULL ORDER BY created_at DESC, updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_control_custom_label(control: str) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM custom_labels WHERE control = ?", (control,)).fetchone()
    return _label_out(row) if row else None


def save_control_custom_label(control: str, elements: list[dict],
                              width_mm: float = 50, tape: int = 24) -> dict | None:
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM custom_labels WHERE control = ?", (control,)).fetchone()
        if existing:
            db.execute(
                "UPDATE custom_labels SET layout_json = ?, width_mm = ?, tape = ?,"
                " updated_at = datetime('now') WHERE control = ?",
                (json.dumps(elements), width_mm, tape, control),
            )
        else:
            db.execute(
                "INSERT INTO custom_labels (id, control, layout_json, width_mm, tape)"
                " VALUES (?, ?, ?, ?, ?)",
                (new_id(), control, json.dumps(elements), width_mm, tape),
            )
    return get_control_custom_label(control)


def create_item(name: str, category: str = "Pantry", unit: str = "pcs",
                package_size: float = 1.0, barcode: str | None = None,
                tracking_mode: str = "binary", concept_id: str | None = None,
                category_explicit: bool = False, quantity: float = 0.0,
                generic_name: str | None = None) -> dict:
    item = {
        "id": new_id(),
        "name": name,
        "category": category,
        "quantity": max(0.0, quantity),
        "unit": unit,
        "min_quantity": 0,
        "package_size": package_size,
        "barcode": barcode,
        "uncertain": 0,
        "tracking_mode": tracking_mode,
    }
    if not concept_id:
        concept_id = catalog.resolve_item_concept(item)
    if concept_id:
        family = catalog.CONCEPTS[concept_id]["family"]
        # family-driven category: a resolved concept is a stronger signal
        # than any OFF/brand heuristic ("Kreuzkümmel" is Spices, even if the
        # OFF category said Snacks) — unless the user just picked a
        # category themselves (manual item creation passes respect=True).
        if not category_explicit:
            item["category"] = catalog.FAMILY_DEFAULT_CATEGORY.get(family, category)
    item["concept_id"] = concept_id
    item["generic_name"] = (generic_name or "").strip() or naming.auto(name, concept_id)
    with get_db() as db:
        db.execute(
            "INSERT INTO items (id, name, category, quantity, unit, min_quantity, package_size, barcode, uncertain, tracking_mode, concept_id, generic_name)"
            " VALUES (:id, :name, :category, :quantity, :unit, :min_quantity, :package_size, :barcode, :uncertain, :tracking_mode, :concept_id, :generic_name)",
            item,
        )
        if barcode:
            db.execute(
                "INSERT OR IGNORE INTO item_barcodes (item_id, barcode) VALUES (?, ?)",
                (item["id"], barcode),
            )
    return _attach_barcodes([item])[0]


def best_name_match(name: str, min_ratio: float = 0.75) -> dict | None:
    items = list_items()
    names = {i["name"].lower(): i for i in items}
    exact = names.get(name.strip().lower())
    if exact:
        return exact
    best, best_ratio = None, min_ratio
    for item in items:
        ratio = difflib.SequenceMatcher(None, name.lower(), item["name"].lower()).ratio()
        if ratio > best_ratio:
            best, best_ratio = item, ratio
    return best


_UNSET = object()


def update_item(item_id: str, min_quantity: float | None = None,
                package_size: float | None = None,
                tracking_mode: str | None = None,
                buy_amount: float | None = None,
                auto_restock: bool | None = None,
                barcode: object = _UNSET,
                name: str | None = None,
                category: str | None = None,
                concept_id: object = _UNSET,
                generic_name: object = _UNSET) -> dict | None:
    """Patch an item. The generic name follows renames and concept changes
    while it is auto-derived; a user-curated one survives until someone
    explicitly replaces or clears it (empty string = re-derive)."""
    with get_db() as db:
        old = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not old:
            return None
        final_name = (name or "").strip() if name is not None else old["name"]
        final_concept = (concept_id or None) if concept_id is not _UNSET \
            else old["concept_id"]
        # follow renames/concept changes only while the stored generic name
        # is still the auto derivation of what is on record
        was_auto = (old["generic_name"] or "").strip().lower() == \
            naming.auto(old["name"], old["concept_id"]).strip().lower()
        if generic_name is _UNSET:
            if was_auto:
                generic_name = naming.auto(final_name, final_concept)
            else:
                generic_name = (old["generic_name"] or "").strip()
        db.execute("UPDATE items SET generic_name = ? WHERE id = ?",
                   ((generic_name or "").strip() or None, item_id))
        if category is not None:
            category = category.strip()
            if not category:
                raise ValueError("category must not be empty")
            db.execute("UPDATE items SET category = ? WHERE id = ?",
                       (category, item_id))
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("item name must not be empty")
            clash = db.execute(
                "SELECT id, name FROM items WHERE lower(name) = lower(?) AND id != ?",
                (name, item_id)).fetchone()
            if clash:
                raise ValueError(f"name already used by {clash['name']}")
            db.execute("UPDATE items SET name = ? WHERE id = ?", (name, item_id))
        if concept_id is not _UNSET:
            # explicit clear ("") or a validated catalog key
            db.execute("UPDATE items SET concept_id = ? WHERE id = ?",
                       (concept_id or None, item_id))
        if min_quantity is not None:
            db.execute("UPDATE items SET min_quantity = ? WHERE id = ?",
                       (min_quantity, item_id))
        if buy_amount is not None:
            db.execute("UPDATE items SET buy_amount = ? WHERE id = ?", (buy_amount, item_id))
        if auto_restock is not None:
            db.execute("UPDATE items SET auto_restock = ? WHERE id = ?",
                       (1 if auto_restock else 0, item_id))
            if auto_restock:
                # enabling on an already-empty item fills the list right away
                row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
                if row and _low_crossed(row["quantity"], row["quantity"], dict(row)):
                    _ensure_on_shopping_list(db, dict(row))
        if package_size is not None:
            db.execute("UPDATE items SET package_size = ? WHERE id = ?", (package_size, item_id))
        if tracking_mode is not None:
            db.execute("UPDATE items SET tracking_mode = ? WHERE id = ?", (tracking_mode, item_id))
        if barcode is not _UNSET:
            # legacy single-barcode patch semantics: replaces the whole set
            db.execute("DELETE FROM item_barcodes WHERE item_id = ?", (item_id,))
            if barcode:
                db.execute(
                    "INSERT OR IGNORE INTO item_barcodes (item_id, barcode) VALUES (?, ?)",
                    (item_id, barcode),
                )
                db.execute("UPDATE items SET barcode = ? WHERE id = ?", (barcode, item_id))
            else:
                db.execute("UPDATE items SET barcode = NULL WHERE id = ?", (item_id,))
    return get_item(item_id)


def _ensure_on_shopping_list(db, item: dict) -> None:
    """Alarm crossed: put the item on the shopping list with its buy quantity."""
    row = db.execute("SELECT 1 FROM shopping_list WHERE item_id = ?", (item["id"],)).fetchone()
    if row:
        return
    add = item["buy_amount"] or item["package_size"] or 1
    db.execute(
        "INSERT INTO shopping_list (item_id, name, amount, unit) VALUES (?, ?, ?, ?)",
        (item["id"], item["name"], add, item["unit"]),
    )


def _low_crossed(before: float, after: float, item: dict) -> bool:
    """Should this change leave the item flagged low — and go on the shopping
    list? With an alarm set, crossing it counts; hitting zero always counts
    only when the item restocks automatically. No alarm, no auto-restock:
    emptying it is a private affair, nothing gets added and the homepage
    stays quiet."""
    minimum = item["min_quantity"] or 0
    always = bool(item.get("auto_restock"))
    if minimum > 0:
        return before > minimum >= after or after <= 0
    return always and after <= 0


def _remove_from_shopping_list_if_stocked(db, item: dict) -> None:
    """Stock rose back above the alarm (binary: in stock again) —
    the pending buy is no longer needed."""
    if item["tracking_mode"] == "binary":
        stocked = (item["quantity"] or 0) > 0
    else:
        stocked = (item["quantity"] or 0) > (item["min_quantity"] or 0)
    if stocked:
        db.execute("DELETE FROM shopping_list WHERE item_id = ?", (item["id"],))


def delete_item(item_id: str) -> dict | None:
    """Remove an item from the pantry: its shopping-list entry goes away
    and linked recipe ingredients fall back to their raw text."""
    with get_db() as db:
        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        db.execute("DELETE FROM shopping_list WHERE item_id = ?", (item_id,))
        db.execute("UPDATE ingredients SET item_id = NULL WHERE item_id = ?", (item_id,))
        db.execute("DELETE FROM item_barcodes WHERE item_id = ?", (item_id,))
        db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    return item


def consume_item(item_id: str, amount: float) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None
        before_qty = row["quantity"]
        if row["tracking_mode"] == "binary":
            # binary tracking: any consumption empties the item
            db.execute(
                "UPDATE items SET quantity = 0, uncertain = 0 WHERE id = ?",
                (item_id,),
            )
            after = 0
        else:
            db.execute(
                "UPDATE items SET quantity = MAX(0, quantity - ?), uncertain = 0 WHERE id = ?",
                (amount, item_id),
            )
            after = db.execute("SELECT quantity FROM items WHERE id = ?", (item_id,)).fetchone()["quantity"]
        item = dict(db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())
        if _low_crossed(before_qty, after, item):
            _ensure_on_shopping_list(db, item)
    return _attach_barcodes([item])[0]


def empty_item(item_id: str) -> dict | None:
    """A tagged container (NFC/QR) reports it is empty: stock goes to
    zero and the item lands on the shopping list."""
    with get_db() as db:
        row = db.execute("SELECT quantity FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None
        db.execute(
            "UPDATE items SET quantity = 0, uncertain = 0 WHERE id = ?",
            (item_id,),
        )
        item = dict(db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())
        if _low_crossed(row["quantity"], 0, item):
            _ensure_on_shopping_list(db, item)
    return item


def restock_item(item_id: str, amount: float) -> dict | None:
    """Stock in outside the receipt flow: quick add of one or more packages."""
    with get_db() as db:
        row = db.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None
        db.execute(
            "UPDATE items SET quantity = quantity + ?, uncertain = 0 WHERE id = ?",
            (amount, item_id),
        )
        item = dict(db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())
        _remove_from_shopping_list_if_stocked(db, item)
    return _attach_barcodes([item])[0]


def confirm_low(item_id: str, is_low: bool) -> dict | None:
    with get_db() as db:
        before = db.execute("SELECT quantity FROM items WHERE id = ?", (item_id,)).fetchone()
        if not before:
            return None
        if is_low:
            db.execute("UPDATE items SET quantity = 0, uncertain = 0 WHERE id = ?", (item_id,))
        else:
            db.execute("UPDATE items SET uncertain = 0 WHERE id = ?", (item_id,))
        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        item = dict(row)
        if is_low and _low_crossed(before["quantity"], item["quantity"], item):
            _ensure_on_shopping_list(db, item)
    return item


def list_receipts() -> list[dict]:
    with get_db() as db:
        receipts = [dict(r) for r in db.execute("SELECT * FROM receipts ORDER BY date DESC, created_at DESC")]
        for receipt in receipts:
            items = db.execute(
                "SELECT id, raw_name, quantity, suggestion, status FROM receipt_items WHERE receipt_id = ?",
                (receipt["id"],),
            ).fetchall()
            receipt["items"] = [dict(i) for i in items]
    return receipts


def create_receipt(store: str, date: str, total: float, items: list[dict],
                   source_file: str | None = None, message_hash: str | None = None) -> dict | None:
    if message_hash:
        with get_db() as db:
            exists = db.execute("SELECT 1 FROM receipts WHERE message_hash = ?", (message_hash,)).fetchone()
        if exists:
            return None
    receipt_id = new_id()
    with get_db() as db:
        db.execute(
            "INSERT INTO receipts (id, store, date, total, status, source_file, message_hash)"
            " VALUES (?, ?, ?, ?, 'review', ?, ?)",
            (receipt_id, store, date, total, source_file, message_hash),
        )
        for item in items:
            db.execute(
                "INSERT INTO receipt_items (id, receipt_id, raw_name, quantity, suggestion, status)"
                " VALUES (?, ?, ?, ?, ?, 'pending')",
                (new_id(), receipt_id, item.get("raw_name", "Unknown"),
                 item.get("quantity", 1), item.get("suggestion")),
            )
    return get_receipt(receipt_id)


def get_receipt(receipt_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
        if not row:
            return None
        receipt = dict(row)
        items = db.execute(
            "SELECT id, raw_name, quantity, suggestion, status FROM receipt_items WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchall()
        receipt["items"] = [dict(i) for i in items]
    return receipt


def match_receipt_item(receipt_id: str, item_id: str, product_name: str) -> dict | None:
    with get_db() as db:
        db.execute(
            "UPDATE receipt_items SET suggestion = ?, status = 'matched' WHERE id = ? AND receipt_id = ?",
            (product_name, item_id, receipt_id),
        )
        # stock in: a receipt item quantity is a number of packages
        row = db.execute("SELECT quantity FROM receipt_items WHERE id = ?", (item_id,)).fetchone()
        line_qty = row["quantity"] or 1
        item = db.execute(
            "SELECT * FROM items WHERE lower(name) = lower(?)", (product_name,)
        ).fetchone()
        if row and item:
            amount_in = line_qty * (item["package_size"] or 1)
            db.execute(
                "UPDATE items SET quantity = quantity + ?, uncertain = 0 WHERE id = ?",
                (amount_in, item["id"]),
            )
            if line_qty >= 2:
                # several packages were entered: the stock is being counted
                db.execute("UPDATE items SET tracking_mode = 'qty' WHERE id = ?", (item["id"],))
            stocked = dict(db.execute("SELECT * FROM items WHERE id = ?", (item["id"],)).fetchone())
            _remove_from_shopping_list_if_stocked(db, stocked)
        pending = db.execute(
            "SELECT COUNT(*) FROM receipt_items WHERE receipt_id = ? AND status = 'pending'",
            (receipt_id,),
        ).fetchone()[0]
        if pending == 0:
            db.execute("UPDATE receipts SET status = 'done' WHERE id = ?", (receipt_id,))
    return get_receipt(receipt_id)


def _recipe_out(recipe: dict) -> dict:
    recipe = dict(recipe)
    recipe["tags"] = _tags(recipe.pop("tags_json", None))
    recipe["step_ingredients"] = _step_links(recipe.pop("step_ingredients_json", None),
                                              len(recipe["steps"]))
    recipe.pop("steps_json", None)
    return recipe


def _step_links(links_json: str | None, step_count: int) -> list[list[dict]]:
    """Stored flat link list -> one list per step. Each link marks the span
    of an ingredient mention; the UI renders the live-scaled "(qty)" there."""
    per_step: list[list[dict]] = [[] for _ in range(max(step_count, 0))]
    try:
        links = json.loads(links_json or "[]")
    except (ValueError, TypeError):
        return per_step
    if not isinstance(links, list):
        return per_step
    for link in links:
        if not isinstance(link, dict):
            continue
        step, ingredient_id = link.get("step"), link.get("ingredient_id")
        if not isinstance(step, int) or not (0 <= step < step_count) or not ingredient_id:
            continue
        per_step[step].append({"ingredient_id": ingredient_id,
                               "start": link.get("start") or 0, "end": link.get("end") or 0,
                               "name": link.get("name") or ""})
    return per_step


def set_step_ingredient_links(recipe_id: str, links: list[dict]) -> dict | None:
    """Persist ingredient mentions in the step texts. LINKS index the
    ingredient entry list; ids are resolved by insertion order (rowid)."""
    with get_db() as db:
        ids = [row["id"] for row in db.execute(
            "SELECT id FROM ingredients WHERE recipe_id = ? ORDER BY rowid",
            (recipe_id,),
        ).fetchall()]
        resolved = []
        for link in links:
            index = link.get("ing")
            if not isinstance(index, int) or not (0 <= index < len(ids)):
                continue
            resolved.append({"step": link["step"], "ingredient_id": ids[index],
                             "start": link["start"], "end": link["end"],
                             "name": link.get("name", "")})
        db.execute("UPDATE recipes SET step_ingredients_json = ? WHERE id = ?",
                   (json.dumps(resolved), recipe_id))
    return get_recipe(recipe_id)


def _tags(tags_json) -> list[str]:
    try:
        tags = json.loads(tags_json or "[]")
        return tags if isinstance(tags, list) else []
    except (ValueError, TypeError):
        return []


def list_recipes() -> list[dict]:
    with get_db() as db:
        recipes = [dict(r) for r in db.execute("SELECT * FROM recipes ORDER BY created_at DESC, title")]
    for recipe in recipes:
        recipe["ingredients"] = _ingredients_for(recipe["id"])
        recipe["steps"] = _steps(recipe["steps_json"])
    return [_recipe_out(r) for r in recipes]


def get_recipe(recipe_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if not row:
        return None
    recipe = dict(row)
    recipe["ingredients"] = _ingredients_for(recipe_id)
    recipe["steps"] = _steps(recipe["steps_json"])
    return _recipe_out(recipe)


def _ingredients_for(recipe_id: str) -> list[dict]:
    # rowid order: alternative-group members are inserted adjacently, so the
    # group stays together in the source list's position
    with get_db() as db:
        rows = db.execute(
            "SELECT id, raw, amount, unit, item_id, tracked, suggestion, alt_group, selected,"
            " concept_id, substitute_kind, substitute_note"
            " FROM ingredients WHERE recipe_id = ? ORDER BY rowid",
            (recipe_id,),
        ).fetchall()
    out = []
    for r in rows:
        ing = dict(r)
        ing["selected"] = bool(ing["selected"])
        out.append(ing)
    return out


def _steps(steps_json: str) -> list[str]:
    import json
    try:
        steps = json.loads(steps_json)
        return steps if isinstance(steps, list) else []
    except (ValueError, TypeError):
        return []


def _insert_ingredients(db, recipe_id: str, ingredients: list[dict]):
    for ing in ingredients:
        generic = (ing.get("generic_name") or "").strip()
        if not generic:
            generic = naming.ingredient_generic_name(
                ing.get("raw") or "", ing.get("concept_id"))
        db.execute(
            "INSERT INTO ingredients (id, recipe_id, raw, amount, unit, item_id, tracked, suggestion,"
            " alt_group, selected, concept_id, substitute_kind, substitute_note, generic_name)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), recipe_id, ing.get("raw", ""), ing.get("amount"), ing.get("unit"),
             ing.get("item_id"), 1 if ing.get("tracked", True) else 0, ing.get("suggestion"),
             ing.get("alt_group"), 1 if ing.get("selected") else 0,
             ing.get("concept_id"), ing.get("substitute_kind"), ing.get("substitute_note"),
             ing.get("generic_name") or generic.strip()),
        )


def create_recipe(title: str, source: str, base_portions: float,
                  ingredients: list[dict], steps: list[str], meta: dict | None = None) -> dict:
    recipe_id = new_id()
    meta = meta or {}
    with get_db() as db:
        db.execute(
            "INSERT INTO recipes (id, title, source, base_portions, steps_json,"
            " prep_minutes, cook_minutes, total_minutes, cuisine, category, tags_json, image_url,"
            " created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (recipe_id, title, source, base_portions, json.dumps(steps),
             meta.get("prep_minutes"), meta.get("cook_minutes"), meta.get("total_minutes"),
             meta.get("cuisine"), meta.get("category"),
             json.dumps(meta.get("tags") or []), meta.get("image_url")),
        )
        _insert_ingredients(db, recipe_id, ingredients)
    return get_recipe(recipe_id)


def update_recipe(recipe_id: str, title: str | None = None, source: str | None = None,
                  base_portions: float | None = None, steps: list[str] | None = None,
                  ingredients: list[dict] | None = None) -> dict | None:
    """Manual recipe edit: update only the given fields; meta (tags, times,
    image) and the creation date stay untouched. `ingredients` replaces the
    whole list (entries carry item matches / alt groups to preserve)."""
    with get_db() as db:
        exists = db.execute("SELECT 1 FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if not exists:
            return None
        if title is not None:
            db.execute("UPDATE recipes SET title = ? WHERE id = ?", (title, recipe_id))
        if source is not None:
            db.execute("UPDATE recipes SET source = ? WHERE id = ?", (source, recipe_id))
        if base_portions is not None:
            db.execute("UPDATE recipes SET base_portions = ? WHERE id = ?", (base_portions, recipe_id))
        if steps is not None:
            db.execute("UPDATE recipes SET steps_json = ? WHERE id = ?", (json.dumps(steps), recipe_id))
        if ingredients is not None:
            db.execute("DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,))
            _insert_ingredients(db, recipe_id, ingredients)
    return get_recipe(recipe_id)


def delete_recipe(recipe_id: str) -> bool:
    with get_db() as db:
        exists = db.execute("SELECT 1 FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if not exists:
            return False
        db.execute("DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,))
        db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    return True


def replace_recipe(recipe_id: str, title: str, source: str, base_portions: float,
                   ingredients: list[dict], steps: list[str], meta: dict | None = None) -> dict | None:
    meta = meta or {}
    with get_db() as db:
        exists = db.execute("SELECT 1 FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if not exists:
            return None
        db.execute(
            "UPDATE recipes SET title = ?, source = ?, base_portions = ?, steps_json = ?,"
            " prep_minutes = ?, cook_minutes = ?, total_minutes = ?, cuisine = ?, category = ?,"
            " tags_json = ?, image_url = ?, created_at = datetime('now')"
            " WHERE id = ?",
            (title, source, base_portions, json.dumps(steps),
             meta.get("prep_minutes"), meta.get("cook_minutes"), meta.get("total_minutes"),
             meta.get("cuisine"), meta.get("category"),
             json.dumps(meta.get("tags") or []), meta.get("image_url"), recipe_id),
        )
        db.execute("DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,))
        _insert_ingredients(db, recipe_id, ingredients)
    return get_recipe(recipe_id)


def match_recipe_ingredient(recipe_id: str, ingredient_id: str, item_id: str, amount: float) -> dict | None:
    with get_db() as db:
        item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        concept_id = catalog.resolve_item_concept(dict(item)) if item else None
        row = db.execute(
            "SELECT substitute_kind, substitute_note FROM ingredients WHERE id = ? AND recipe_id = ?",
            (ingredient_id, recipe_id)).fetchone()
        # a confirmed variant/blend/sibling suggestion stays marked as a
        # substitute (the user chose "use this instead"); identity rows
        # drop the mark because the concept itself matches
        kind = row["substitute_kind"] if row and row["substitute_kind"] in (
            "variant", "in_blend", "sibling") else None
        note = row["substitute_note"] if row else None
        if kind is None:
            note = None
        db.execute(
            "UPDATE ingredients SET item_id = ?, amount = ?, suggestion = NULL, tracked = 1,"
            " concept_id = ?, substitute_kind = ?, substitute_note = ?"
            " WHERE id = ? AND recipe_id = ?",
            (item_id, amount, concept_id, kind, note, ingredient_id, recipe_id),
        )
    return get_recipe(recipe_id)


def merge_ingredient_rows(updates: list[dict]) -> int:
    """Settings > Missing items, merge: relink several ingredient rows to
    the chosen inventory item in one pass, rewriting their raw text to
    name it. Confirmed identity merge -- substitute marks and buy/alias
    suggestions drop away."""
    with get_db() as db:
        for u in updates:
            db.execute(
                "UPDATE ingredients SET raw = ?, amount = ?, unit = ?,"
                " item_id = ?, concept_id = ?,"
                " suggestion = NULL, substitute_kind = NULL, substitute_note = NULL,"
                " tracked = 1 WHERE id = ? AND recipe_id = ?",
                (u["raw"], u["amount"], u["unit"], u["item_id"], u["concept_id"],
                 u["ingredient_id"], u["recipe_id"]))
    return len(updates)


STANDARDIZE_FIELDS = {"item_id", "suggestion", "tracked", "concept_id",
                      "substitute_kind", "substitute_note"}


def standardize_ingredient(recipe_id: str, ingredient_id: str, fields: dict) -> None:
    """Update specific match fields of one ingredient row (catalog
    standardize job). Whitelisted columns only."""
    sets, vals = [], []
    for key, value in fields.items():
        if key not in STANDARDIZE_FIELDS:
            raise ValueError(f"field {key} not standardizable")
        sets.append(f"{key} = ?")
        vals.append(value)
    if not sets:
        return
    vals.extend([ingredient_id, recipe_id])
    with get_db() as db:
        db.execute(
            f"UPDATE ingredients SET {', '.join(sets)} WHERE id = ? AND recipe_id = ?",
            vals,
        )


def delete_ingredient(recipe_id: str, ingredient_id: str) -> bool:
    with get_db() as db:
        cursor = db.execute(
            "DELETE FROM ingredients WHERE id = ? AND recipe_id = ?",
            (ingredient_id, recipe_id),
        )
        return cursor.rowcount > 0


def set_item_concept(item_id: str, concept_id: str | None) -> None:
    with get_db() as db:
        db.execute("UPDATE items SET concept_id = ? WHERE id = ?",
                   (concept_id, item_id))


def select_recipe_ingredient(recipe_id: str, ingredient_id: str) -> dict | None:
    """Pick one option of an and/or alternative group ("basmati rice or
    naan"): marks it selected and clears the flag on its group siblings."""
    with get_db() as db:
        row = db.execute(
            "SELECT alt_group FROM ingredients WHERE id = ? AND recipe_id = ?",
            (ingredient_id, recipe_id),
        ).fetchone()
        if not row:
            return None
        if row["alt_group"]:
            db.execute(
                "UPDATE ingredients SET selected = CASE WHEN id = ? THEN 1 ELSE 0 END"
                " WHERE recipe_id = ? AND alt_group = ?",
                (ingredient_id, recipe_id, row["alt_group"]),
            )
        else:
            db.execute("UPDATE ingredients SET selected = 1 WHERE id = ?", (ingredient_id,))
    return get_recipe(recipe_id)


def _chosen_group_member(ing: dict, all_ingredients: list[dict]) -> dict | None:
    """The one group member that counts for shopping/cooking: the user's
    pick, or None while the group hasn't been decided yet."""
    if not ing.get("alt_group"):
        return ing
    choices = [i for i in all_ingredients if i.get("alt_group") == ing["alt_group"]]
    return next((i for i in choices if i.get("selected")), None)


def list_shopping_list() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT item_id, name, amount, unit FROM shopping_list ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def add_to_shopping_list(item_id: str, amount: float) -> list[dict]:
    item = get_item(item_id)
    if not item:
        raise KeyError(item_id)
    with get_db() as db:
        row = db.execute("SELECT amount FROM shopping_list WHERE item_id = ?", (item_id,)).fetchone()
        if row:
            db.execute("UPDATE shopping_list SET amount = amount + ? WHERE item_id = ?", (amount, item_id))
        else:
            db.execute(
                "INSERT INTO shopping_list (item_id, name, amount, unit) VALUES (?, ?, ?, ?)",
                (item_id, item["name"], amount, item["unit"]),
            )
    return list_shopping_list()


def remove_from_shopping_list(item_id: str) -> list[dict]:
    with get_db() as db:
        db.execute("DELETE FROM shopping_list WHERE item_id = ?", (item_id,))
    return list_shopping_list()


def _match_or_create_item(db, name: str, unit: str | None) -> dict:
    """Resolve a suggested product name against the pantry within one open
    connection: exact name first, then the usual fuzzy match, else a new
    item with zero stock so it can be bought."""
    name = name.strip()
    if not name:
        raise ValueError("empty item name")
    row = db.execute("SELECT * FROM items WHERE lower(name) = lower(?)", (name,)).fetchone()
    if row:
        return dict(row)
    best, best_ratio = None, 0.75
    for row in db.execute("SELECT * FROM items").fetchall():
        ratio = difflib.SequenceMatcher(None, name.lower(), row["name"].lower()).ratio()
        if ratio > best_ratio:
            best, best_ratio = dict(row), ratio
    if best:
        return best
    item = {
        "id": new_id(),
        "name": name,
        "category": "Pantry",
        "quantity": 0,
        "unit": unit or "pcs",
        "min_quantity": 0,
        "package_size": 1,
        "barcode": None,
        "uncertain": 0,
        "tracking_mode": "binary",
        "buy_amount": None,
    }
    db.execute(
        "INSERT INTO items (id, name, category, quantity, unit, min_quantity, package_size, barcode, uncertain, tracking_mode)"
        " VALUES (:id, :name, :category, :quantity, :unit, :min_quantity, :package_size, :barcode, :uncertain, :tracking_mode)",
        item,
    )
    return item


def _ingredient_amount(ing: dict) -> float:
    if ing["amount"] is not None:
        return ing["amount"]
    numbers = re.findall(r"\d+(?:[.,]\d+)?", ing["raw"] or "")
    return float(numbers[0].replace(",", ".")) if numbers else 1.0


def add_missing_to_shopping_list(recipe: dict, items_by_id: dict, portions: float) -> list[dict]:
    base = recipe["base_portions"] or 1
    with get_db() as db:
        seen_groups = set()
        for ing in recipe["ingredients"]:
            group = ing.get("alt_group")
            effective = ing
            if group:
                if group in seen_groups:
                    continue
                seen_groups.add(group)
                # and/or group: only the picked option goes on the list,
                # an undecided group waits until one option is selected
                effective = _chosen_group_member(ing, recipe["ingredients"])
                if effective is None:
                    continue
            # anything goes on the list as long as it's quantifiable
            # (no measurable amount and no number in the raw line -> skip);
            # a picked alternative always buys its package, amount or not
            if not group and effective["amount"] is None and not re.findall(r"\d+(?:[.,]\d+)?", effective["raw"] or ""):
                continue
            item = items_by_id.get(effective["item_id"]) if effective["item_id"] else None
            if item is None and effective["item_id"]:
                continue
            amount = _ingredient_amount(effective)
            if item is None:
                name = (effective["suggestion"] or effective["raw"] or "").strip()
                if not name:
                    continue
                item = _match_or_create_item(db, name, effective["unit"])
                db.execute(
                    "UPDATE ingredients SET item_id = ?, amount = ?, suggestion = NULL, tracked = 1"
                    " WHERE id = ?",
                    (item["id"], amount, effective["id"]),
                )
            elif effective["amount"] is None:
                db.execute("UPDATE ingredients SET amount = ? WHERE id = ?", (amount, effective["id"]))
            if item["tracking_mode"] == "binary":
                # binary: any not-in-stock item goes on the list as one buy
                # amount; the recipe requirement is not compared numerically
                if item["quantity"] > 0:
                    continue
                row = db.execute("SELECT 1 FROM shopping_list WHERE item_id = ?", (item["id"],)).fetchone()
                if not row:
                    add = item["buy_amount"] or item["package_size"] or 1
                    db.execute(
                        "INSERT INTO shopping_list (item_id, name, amount, unit) VALUES (?, ?, ?, ?)",
                        (item["id"], item["name"], add, item["unit"]),
                    )
                continue
            required = amount * portions / base
            missing = required - item["quantity"]
            if missing <= 1e-9:
                continue
            package = item["package_size"] or 1
            add = round(-(-missing // package) * package, 3)
            row = db.execute("SELECT amount FROM shopping_list WHERE item_id = ?", (item["id"],)).fetchone()
            if row:
                db.execute("UPDATE shopping_list SET amount = amount + ? WHERE item_id = ?", (add, item["id"]))
            else:
                db.execute(
                    "INSERT INTO shopping_list (item_id, name, amount, unit) VALUES (?, ?, ?, ?)",
                    (item["id"], item["name"], add, item["unit"]),
                )
    return list_shopping_list()


def cook_recipe(recipe: dict, portions: float) -> list[dict]:
    base = recipe["base_portions"] or 1
    with get_db() as db:
        seen_groups = set()
        for ing in recipe["ingredients"]:
            if ing.get("alt_group"):
                # cook deducts the picked option only ("rice or naan");
                # an undecided group stays untouched
                if ing["alt_group"] in seen_groups or not ing.get("selected"):
                    continue
                seen_groups.add(ing["alt_group"])
            if not ing["item_id"] or ing["amount"] is None:
                continue
            used = ing["amount"] * portions / base
            before = db.execute("SELECT * FROM items WHERE id = ?", (ing["item_id"],)).fetchone()
            if not before:
                continue
            if before["tracking_mode"] == "binary":
                # binary tracking: cooking only raises the "might be running
                # low" question; the amount stays on record for prognosis
                if before["quantity"] > 0:
                    db.execute(
                        "UPDATE items SET uncertain = 1 WHERE id = ?",
                        (ing["item_id"],),
                    )
                continue
            db.execute(
                "UPDATE items SET quantity = MAX(0, quantity - ?),"
                " uncertain = CASE WHEN MAX(0, quantity - ?) <= min_quantity THEN 1 ELSE uncertain END"
                " WHERE id = ?",
                (used, used, ing["item_id"]),
            )
            row = db.execute("SELECT * FROM items WHERE id = ?", (ing["item_id"],)).fetchone()
            if row and _low_crossed(before["quantity"], row["quantity"], dict(row)):
                _ensure_on_shopping_list(db, dict(row))
    return list_items()
