import re
from datetime import date, timedelta

from .db import get_db
from .repo import new_id

WEEK_DAYS = 7


def normalize_week(week_start: str) -> str:
    d = date.fromisoformat(week_start)
    return (d - timedelta(days=d.weekday())).isoformat()


def _persons_for(db, meal_ids: list[str]) -> dict[str, list[dict]]:
    if not meal_ids:
        return {}
    marks = ",".join("?" for _ in meal_ids)
    rows = db.execute(
        f"SELECT mp.meal_id, p.id, p.name FROM plan_meal_persons mp"
        f" JOIN plan_persons p ON p.id = mp.person_id"
        f" WHERE mp.meal_id IN ({marks}) ORDER BY p.name",
        meal_ids,
    ).fetchall()
    out: dict[str, list[dict]] = {mid: [] for mid in meal_ids}
    for row in rows:
        out[row["meal_id"]].append({"id": row["id"], "name": row["name"]})
    return out


def _fills_for(db, meal_ids: list[str]) -> dict[str, list[dict]]:
    if not meal_ids:
        return {}
    marks = ",".join("?" for _ in meal_ids)
    rows = db.execute(
        f"SELECT f.*, r.title AS recipe_title, pp.name AS prepared_name, pr.name AS person_name,"
        f" CASE WHEN pr.id IS NULL THEN NULL ELSE f.person_id END AS person_id"
        f" FROM plan_fills f"
        f" LEFT JOIN recipes r ON r.id = f.recipe_id"
        f" LEFT JOIN plan_prepared pp ON pp.id = f.prepared_id"
        f" LEFT JOIN plan_persons pr ON pr.id = f.person_id"
        f" WHERE f.meal_id IN ({marks}) ORDER BY f.portions",
        meal_ids,
    ).fetchall()
    out: dict[str, list[dict]] = {mid: [] for mid in meal_ids}
    for row in rows:
        out[row["meal_id"]].append(
            {
                "id": row["id"],
                "meal_id": row["meal_id"],
                "recipe_id": row["recipe_id"],
                "recipe_title": row["recipe_title"],
                "prepared_id": row["prepared_id"],
                "prepared_name": row["prepared_name"],
                "person_id": row["person_id"],
                "person_name": row["person_name"],
                "portions": row["portions"],
                "prep_multiplier": row["prep_multiplier"],
            }
        )
    return out


def list_prepared() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM plan_prepared ORDER BY name").fetchall()
        placed = {
            row["prepared_id"]: row["total"]
            for row in db.execute(
                "SELECT prepared_id, SUM(portions) AS total FROM plan_fills"
                " WHERE prepared_id IS NOT NULL GROUP BY prepared_id"
            )
        }
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "recipe_id": row["recipe_id"],
                "portions": row["portions"],
                "manual": bool(row["manual"]),
                "placed": placed.get(row["id"], 0),
                "available": max(0, row["portions"] - placed.get(row["id"], 0)),
            }
            for row in rows
        ]


def list_persons() -> list[dict]:
    with get_db() as db:
        return [dict(row) for row in db.execute("SELECT * FROM plan_persons ORDER BY name")]


def plan_payload(week_start: str) -> dict:
    week = normalize_week(week_start)
    with get_db() as db:
        meals = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM plan_meals WHERE week_start = ?"
                " ORDER BY day, rowid",
                (week,),
            )
        ]
        meal_ids = [m["id"] for m in meals]
        persons = _persons_for(db, meal_ids)
        fills = _fills_for(db, meal_ids)
    for meal in meals:
        meal["persons"] = persons.get(meal["id"], [])
        meal["fills"] = fills.get(meal["id"], [])
    return {
        "week_start": week,
        "persons": list_persons(),
        "meals": meals,
        "prepared": list_prepared(),
    }


def add_person(name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    pid = new_id()
    with get_db() as db:
        db.execute("INSERT INTO plan_persons (id, name) VALUES (?, ?)", (pid, name))
    return plan_payload(_current_week())


def remove_person(person_id: str) -> dict:
    with get_db() as db:
        db.execute("DELETE FROM plan_persons WHERE id = ?", (person_id,))
    return plan_payload(_current_week())


def _current_week() -> str:
    return normalize_week(date.today().isoformat())


def _placed_portions(db, prepared_id: str) -> float:
    row = db.execute(
        "SELECT SUM(portions) AS total FROM plan_fills WHERE prepared_id = ?",
        (prepared_id,),
    ).fetchone()
    return row["total"] or 0


def add_meal(week_start: str, day: int, meal: str, person_ids: list[str]) -> dict:
    week = normalize_week(week_start)
    meal = meal.strip()
    if not meal:
        raise ValueError("meal must not be empty")
    if day < 0 or day >= WEEK_DAYS:
        raise ValueError("day must be 0-6 (Monday-Sunday)")
    mid = new_id()
    with get_db() as db:
        db.execute(
            "INSERT INTO plan_meals (id, week_start, day, meal) VALUES (?, ?, ?, ?)",
            (mid, week, day, meal),
        )
        for person_id in person_ids:
            db.execute(
                "INSERT OR IGNORE INTO plan_meal_persons (meal_id, person_id) VALUES (?, ?)",
                (mid, person_id),
            )
    return plan_payload(week)


def _week_of_meal(db, meal_id: str) -> str | None:
    row = db.execute("SELECT week_start FROM plan_meals WHERE id = ?", (meal_id,)).fetchone()
    return row["week_start"] if row else None


def toggle_meal_person(meal_id: str, person_id: str) -> dict:
    with get_db() as db:
        week = _week_of_meal(db, meal_id)
        row = db.execute(
            "SELECT 1 FROM plan_meal_persons WHERE meal_id = ? AND person_id = ?",
            (meal_id, person_id),
        ).fetchone()
        if row:
            db.execute(
                "DELETE FROM plan_meal_persons WHERE meal_id = ? AND person_id = ?",
                (meal_id, person_id),
            )
        else:
            db.execute(
                "INSERT INTO plan_meal_persons (meal_id, person_id) VALUES (?, ?)",
                (meal_id, person_id),
            )
    if week is None:
        raise LookupError("meal not found")
    return plan_payload(week)


def remove_meal(meal_id: str) -> dict:
    with get_db() as db:
        week = _week_of_meal(db, meal_id)
        if week:
            db.execute("DELETE FROM plan_meals WHERE id = ?", (meal_id,))
    if week is None:
        raise LookupError("meal not found")
    return plan_payload(week)


def add_fill(
    meal_id: str,
    recipe_id: str | None = None,
    prepared_id: str | None = None,
    portions: float = 1,
    prep_multiplier: float = 0,
    person_id: str | None = None,
    person_ids: list[str] | None = None,
) -> dict:
    """Add a fill to a meal. `person_ids` are attached to the meal (who eats
    it, if not linked yet); `person_id` additionally tags the fill itself, for
    drops onto a divided per-person field."""
    if (recipe_id is None) == (prepared_id is None):
        raise ValueError("exactly one of recipe_id or prepared_id is required")
    with get_db() as db:
        week = _week_of_meal(db, meal_id)
        if week is None:
            raise LookupError("meal not found")
        attach = [pid for pid in (person_ids or []) if pid]
        if person_id and person_id not in attach:
            attach.append(person_id)
        for pid in attach:
            db.execute(
                "INSERT OR IGNORE INTO plan_meal_persons (meal_id, person_id) VALUES (?, ?)",
                (meal_id, pid),
            )
        placed_portions = max(1, round(portions))
        if prepared_id:
            row = db.execute("SELECT * FROM plan_prepared WHERE id = ?", (prepared_id,)).fetchone()
            if not row:
                raise LookupError("prepared meal not found")
            available = row["portions"] - _placed_portions(db, prepared_id)
            if available < 1:
                raise ValueError("no portions of this prepared meal left")
            placed_portions = min(placed_portions, int(available))
            db.execute(
                "INSERT INTO plan_fills (id, meal_id, prepared_id, person_id, portions) VALUES (?, ?, ?, ?, ?)",
                (new_id(), meal_id, prepared_id, person_id, placed_portions),
            )
        else:
            recipe = repo_get_recipe(recipe_id)
            if not recipe:
                raise LookupError("recipe not found")
            prep = max(0, round(prep_multiplier))
            if prep > 0:
                db.execute(
                    "INSERT INTO plan_prepared (id, name, recipe_id, portions, manual) VALUES (?, ?, ?, ?, 0)",
                    (new_id(), f"{recipe['title']} (prep)", recipe_id, prep * max(1, recipe["base_portions"] or 1)),
                )
            db.execute(
                "INSERT INTO plan_fills (id, meal_id, recipe_id, person_id, portions, prep_multiplier)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (new_id(), meal_id, recipe_id, person_id, max(1, round(portions)), prep),
            )
    return plan_payload(week)


def remove_fill(fill_id: str) -> dict:
    with get_db() as db:
        row = db.execute(
            "SELECT m.week_start FROM plan_fills f JOIN plan_meals m ON m.id = f.meal_id"
            " WHERE f.id = ?",
            (fill_id,),
        ).fetchone()
        if not row:
            raise LookupError("fill not found")
        week = row["week_start"]
        db.execute("DELETE FROM plan_fills WHERE id = ?", (fill_id,))
    return plan_payload(week)


def add_prepared(name: str, portions: float) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    with get_db() as db:
        db.execute(
            "INSERT INTO plan_prepared (id, name, portions, manual) VALUES (?, ?, ?, 1)",
            (new_id(), name, max(1, round(portions))),
        )
    return plan_payload(_current_week())


def remove_prepared(prepared_id: str) -> dict:
    with get_db() as db:
        db.execute("DELETE FROM plan_prepared WHERE id = ?", (prepared_id,))
    return plan_payload(_current_week())


def _ingredient_amount(ing: dict) -> float:
    if ing["amount"] is not None:
        return ing["amount"]
    numbers = re.findall(r"\d+(?:[.,]\d+)?", ing["raw"] or "")
    return float(numbers[0].replace(",", ".")) if numbers else 1.0


def _week_recipe_totals(week: str) -> dict[str, float]:
    """recipe_id -> (portions eaten + portions prepared), both scaled to
    ingredient quantities via base_portions later."""
    with get_db() as db:
        rows = db.execute(
            "SELECT f.recipe_id, SUM(f.portions) AS portions, SUM(f.prep_multiplier) AS prep"
            " FROM plan_fills f JOIN plan_meals m ON m.id = f.meal_id"
            " WHERE m.week_start = ? AND f.recipe_id IS NOT NULL"
            " GROUP BY f.recipe_id",
            (week,),
        ).fetchall()
        return {
            row["recipe_id"]: {"portions": row["portions"] or 0, "prep": row["prep"] or 0}
            for row in rows
        }


def week_shopping_list(week_start: str) -> list[dict]:
    week = normalize_week(week_start)
    from . import repo

    totals = _week_recipe_totals(week)
    if not totals:
        return []
    recipes = {
        r["id"]: r
        for r in (repo.get_recipe(recipe_id) for recipe_id in totals)
        if r
    }
    items = {i["id"]: i for i in repo.list_items()}
    aggregated: dict[str, dict] = {}
    for recipe_id, total in totals.items():
        recipe = recipes.get(recipe_id)
        if not recipe:
            continue
        base = recipe["base_portions"] or 1
        scale = (total["portions"] + total["prep"]) / base
        seen_groups = set()
        for ing in recipe["ingredients"]:
            if ing.get("alt_group"):
                if ing["alt_group"] in seen_groups or not ing.get("selected"):
                    continue
                seen_groups.add(ing["alt_group"])
            # anything counts as long as it's quantifiable, same rule as
            # add-missing: no measurable amount and no number -> skip
            if not ing.get("alt_group") and ing["amount"] is None and not re.findall(r"\d+(?:[.,]\d+)?", ing["raw"] or ""):
                continue
            if ing["item_id"] is None:
                name = (ing["suggestion"] or ing["raw"] or "").strip()
                if not name:
                    continue
                key = f"~{name.lower()}"
                if key not in aggregated:
                    aggregated[key] = {"item_id": None, "name": name, "amount": 0, "unit": ing["unit"] or "pcs"}
            else:
                key = ing["item_id"]
                item = items.get(key)
                if item is None:
                    continue
                if key not in aggregated:
                    aggregated[key] = {
                        "item_id": key,
                        "name": item["name"],
                        "amount": 0,
                        "unit": item["unit"],
                    }
            aggregated[key]["amount"] += round(_ingredient_amount(ing) * scale, 3)
    out = []
    for entry in aggregated.values():
        item = items.get(entry["item_id"]) if entry["item_id"] else None
        if item is not None:
            if item["tracking_mode"] == "binary":
                if item["quantity"] > 0:
                    continue
                entry["amount"] = item["package_size"] or 1
            else:
                missing = entry["amount"] - item["quantity"]
                if missing <= 1e-9:
                    continue
                package = item["package_size"] or 1
                entry["amount"] = round(-(-missing // package) * package, 3)
        out.append(entry)
    out.sort(key=lambda e: e["name"].lower())
    return out


def push_week_shopping_list(week_start: str) -> list[dict]:
    entries = week_shopping_list(week_start)
    with get_db() as db:
        for entry in entries:
            if entry["item_id"] is None:
                continue
            row = db.execute(
                "SELECT amount FROM shopping_list WHERE item_id = ?", (entry["item_id"],)
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE shopping_list SET amount = amount + ? WHERE item_id = ?",
                    (entry["amount"], entry["item_id"]),
                )
            else:
                db.execute(
                    "INSERT INTO shopping_list (item_id, name, amount, unit) VALUES (?, ?, ?, ?)",
                    (entry["item_id"], entry["name"], entry["amount"], entry["unit"]),
                )
    from . import repo

    return repo.list_shopping_list()


def repo_get_recipe(recipe_id: str):
    from . import repo

    return repo.get_recipe(recipe_id)
