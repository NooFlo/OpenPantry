import difflib
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
                package_size: float = 1.0, barcode: str | None = None) -> dict:
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
    }
    with get_db() as db:
        db.execute(
            "INSERT INTO items (id, name, category, quantity, unit, min_quantity, package_size, barcode, uncertain)"
            " VALUES (:id, :name, :category, :quantity, :unit, :min_quantity, :package_size, :barcode, :uncertain)",
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


def consume_item(item_id: str, amount: float) -> dict | None:
    with get_db() as db:
        db.execute(
            "UPDATE items SET quantity = MAX(0, quantity - ?), uncertain = 0 WHERE id = ?",
            (amount, item_id),
        )
        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def confirm_low(item_id: str, is_low: bool) -> dict | None:
    with get_db() as db:
        if is_low:
            db.execute("UPDATE items SET quantity = 0, uncertain = 0 WHERE id = ?", (item_id,))
        else:
            db.execute("UPDATE items SET uncertain = 0 WHERE id = ?", (item_id,))
        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


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
        pending = db.execute(
            "SELECT COUNT(*) FROM receipt_items WHERE receipt_id = ? AND status = 'pending'",
            (receipt_id,),
        ).fetchone()[0]
        if pending == 0:
            db.execute("UPDATE receipts SET status = 'done' WHERE id = ?", (receipt_id,))
    return get_receipt(receipt_id)


def list_recipes() -> list[dict]:
    with get_db() as db:
        recipes = [dict(r) for r in db.execute("SELECT * FROM recipes ORDER BY title")]
    for recipe in recipes:
        recipe["ingredients"] = _ingredients_for(recipe["id"])
        recipe["steps"] = _steps(recipe["steps_json"])
        del recipe["steps_json"]
    return recipes


def get_recipe(recipe_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if not row:
        return None
    recipe = dict(row)
    recipe["ingredients"] = _ingredients_for(recipe_id)
    recipe["steps"] = _steps(recipe["steps_json"])
    del recipe["steps_json"]
    return recipe


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


def create_recipe(title: str, source: str, base_portions: float,
                  ingredients: list[dict], steps: list[str]) -> dict:
    import json
    recipe_id = new_id()
    with get_db() as db:
        db.execute(
            "INSERT INTO recipes (id, title, source, base_portions, steps_json) VALUES (?, ?, ?, ?, ?)",
            (recipe_id, title, source, base_portions, json.dumps(steps)),
        )
        for ing in ingredients:
            db.execute(
                "INSERT INTO ingredients (id, recipe_id, raw, amount, unit, item_id, tracked, suggestion)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id(), recipe_id, ing.get("raw", ""), ing.get("amount"), ing.get("unit"),
                 ing.get("item_id"), 1 if ing.get("tracked", True) else 0, ing.get("suggestion")),
            )
    return get_recipe(recipe_id)


def match_recipe_ingredient(recipe_id: str, ingredient_id: str, item_id: str, amount: float) -> dict | None:
    with get_db() as db:
        db.execute(
            "UPDATE ingredients SET item_id = ?, amount = ?, suggestion = NULL, tracked = 1"
            " WHERE id = ? AND recipe_id = ?",
            (item_id, amount, ingredient_id, recipe_id),
        )
    return get_recipe(recipe_id)


def untrack_recipe_ingredient(recipe_id: str, ingredient_id: str) -> dict | None:
    with get_db() as db:
        db.execute(
            "UPDATE ingredients SET tracked = 0, suggestion = NULL, item_id = NULL WHERE id = ? AND recipe_id = ?",
            (ingredient_id, recipe_id),
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


def add_missing_to_shopping_list(recipe: dict, items_by_id: dict, portions: float) -> list[dict]:
    base = recipe["base_portions"] or 1
    for ing in recipe["ingredients"]:
        if not ing["tracked"] or not ing["item_id"] or ing["amount"] is None:
            continue
        item = items_by_id.get(ing["item_id"])
        if not item:
            continue
        required = ing["amount"] * portions / base
        missing = required - item["quantity"]
        if missing <= 1e-9:
            continue
        package = item["package_size"] or 1
        add = -(-missing // package) * package
        add = round(add, 3)
        with get_db() as db:
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
            if not ing["tracked"] or not ing["item_id"] or ing["amount"] is None:
                continue
            used = ing["amount"] * portions / base
            db.execute(
                "UPDATE items SET quantity = MAX(0, quantity - ?),"
                " uncertain = CASE WHEN MAX(0, quantity - ?) <= min_quantity THEN 1 ELSE uncertain END"
                " WHERE id = ?",
                (used, used, ing["item_id"]),
            )
    return list_items()
