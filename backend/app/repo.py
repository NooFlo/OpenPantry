import difflib
import json
import re
import uuid

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


def list_items() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM items ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def get_item(item_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def find_item_by_name(name: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM items WHERE lower(name) = lower(?)", (name,)).fetchone()
    return dict(row) if row else None


def find_item_by_barcode(barcode: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM items WHERE barcode = ?", (barcode,)).fetchone()
    return dict(row) if row else None


def create_item(name: str, category: str = "Pantry", unit: str = "pcs",
                package_size: float = 1.0, barcode: str | None = None,
                tracking_mode: str = "binary") -> dict:
    item = {
        "id": new_id(),
        "name": name,
        "category": category,
        "quantity": 0,
        "unit": unit,
        "min_quantity": 0,
        "package_size": package_size,
        "barcode": barcode,
        "uncertain": 0,
        "tracking_mode": tracking_mode,
    }
    with get_db() as db:
        db.execute(
            "INSERT INTO items (id, name, category, quantity, unit, min_quantity, package_size, barcode, uncertain, tracking_mode)"
            " VALUES (:id, :name, :category, :quantity, :unit, :min_quantity, :package_size, :barcode, :uncertain, :tracking_mode)",
            item,
        )
    return item


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


def update_item(item_id: str, min_quantity: float | None = None,
                package_size: float | None = None,
                tracking_mode: str | None = None) -> dict | None:
    with get_db() as db:
        if min_quantity is not None:
            db.execute("UPDATE items SET min_quantity = ? WHERE id = ?", (min_quantity, item_id))
        if package_size is not None:
            db.execute("UPDATE items SET package_size = ? WHERE id = ?", (package_size, item_id))
        if tracking_mode is not None:
            db.execute("UPDATE items SET tracking_mode = ? WHERE id = ?", (tracking_mode, item_id))
    return get_item(item_id)


def _ensure_on_shopping_list(db, item: dict) -> None:
    """Alarm crossed: put the item on the shopping list with its buy quantity."""
    row = db.execute("SELECT 1 FROM shopping_list WHERE item_id = ?", (item["id"],)).fetchone()
    if row:
        return
    add = item["package_size"] or 1
    db.execute(
        "INSERT INTO shopping_list (item_id, name, amount, unit) VALUES (?, ?, ?, ?)",
        (item["id"], item["name"], add, item["unit"]),
    )


def _low_crossed(before: float, after: float, item: dict) -> bool:
    """The stock fell to the alarm level, or ran out entirely."""
    minimum = item["min_quantity"] or 0
    return (minimum > 0 and before > minimum >= after) or after <= 0


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
    return item


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
    return item


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
    recipe.pop("steps_json", None)
    return recipe


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
    with get_db() as db:
        rows = db.execute(
            "SELECT id, raw, amount, unit, item_id, tracked, suggestion FROM ingredients WHERE recipe_id = ?",
            (recipe_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _steps(steps_json: str) -> list[str]:
    import json
    try:
        steps = json.loads(steps_json)
        return steps if isinstance(steps, list) else []
    except (ValueError, TypeError):
        return []


def _insert_ingredients(db, recipe_id: str, ingredients: list[dict]):
    for ing in ingredients:
        db.execute(
            "INSERT INTO ingredients (id, recipe_id, raw, amount, unit, item_id, tracked, suggestion)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), recipe_id, ing.get("raw", ""), ing.get("amount"), ing.get("unit"),
             ing.get("item_id"), 1 if ing.get("tracked", True) else 0, ing.get("suggestion")),
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
        db.execute(
            "UPDATE ingredients SET item_id = ?, amount = ?, suggestion = NULL, tracked = 1"
            " WHERE id = ? AND recipe_id = ?",
            (item_id, amount, ingredient_id, recipe_id),
        )
    return get_recipe(recipe_id)


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
        for ing in recipe["ingredients"]:
            # anything goes on the list as long as it's quantifiable
            # (no measurable amount and no number in the raw line -> skip)
            if ing["amount"] is None and not re.findall(r"\d+(?:[.,]\d+)?", ing["raw"] or ""):
                continue
            item = items_by_id.get(ing["item_id"]) if ing["item_id"] else None
            if item is None and ing["item_id"]:
                continue
            amount = _ingredient_amount(ing)
            if item is None:
                name = (ing["suggestion"] or ing["raw"] or "").strip()
                if not name:
                    continue
                item = _match_or_create_item(db, name, ing["unit"])
                db.execute(
                    "UPDATE ingredients SET item_id = ?, amount = ?, suggestion = NULL, tracked = 1"
                    " WHERE id = ?",
                    (item["id"], amount, ing["id"]),
                )
            elif ing["amount"] is None:
                db.execute("UPDATE ingredients SET amount = ? WHERE id = ?", (amount, ing["id"]))
            if item["tracking_mode"] == "binary":
                # binary: any not-in-stock item goes on the list as one buy
                # amount; the recipe requirement is not compared numerically
                if item["quantity"] > 0:
                    continue
                row = db.execute("SELECT 1 FROM shopping_list WHERE item_id = ?", (item["id"],)).fetchone()
                if not row:
                    add = item["package_size"] or 1
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
        for ing in recipe["ingredients"]:
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
