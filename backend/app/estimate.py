"""Projected stock estimates.

The persisted `items.quantity` is the truth of record: scans and cooks
write it directly. This module projects on top of it — quantity minus
what planned-but-uncooked meals still need — so the Home screen can ask
"might this run low?" *before* the jar is empty. Impromptu cooking
without the app never touches the projection: it doesn't log, it only
shifts when the next scan (BOUGHT / package-empty) snaps reality back
in. A "No" on the prompt snoozes it until the estimate falls further.
"""

from .db import get_db


def committed_by_item() -> dict[str, float]:
    """Per item: how much of it planned (un-cooked) meals still need.

    Mirrors cook_recipe's arithmetic: a fill needs
    `amount * fill_portions / base_portions` of every quantified,
    item-matched ingredient row. Unquantified rows never contributed a
    number to deduct, so they don't contribute a projection either.
    """
    with get_db() as db:
        rows = db.execute(
            """
            SELECT ri.item_id AS item_id,
                   SUM(ri.amount * (f.portions + f.prep_multiplier)
                       / MAX(r.base_portions, 1)) AS needed
            FROM plan_fills f
            JOIN plan_meals m ON m.id = f.meal_id
            JOIN recipes r ON r.id = f.recipe_id
            JOIN ingredients ri ON ri.recipe_id = r.id
            WHERE ri.tracked = 1 AND ri.amount IS NOT NULL AND ri.item_id IS NOT NULL
            GROUP BY ri.item_id
            """
        ).fetchall()
    return {row["item_id"]: row["needed"] for row in rows}


def projections(items: list[dict] | None = None) -> dict[str, dict]:
    """Per item: `estimate` (quantity minus planned need, >= 0), `committed`
    (the planned need itself), `low` (hard fact: quantity at or under the
    alarm) and `low_projected` (plan-driven dip: the estimate touches the
    alarm only after the planned meals cook). A dismissed prompt stays down
    until the estimate falls below the level it was dismissed at — planning
    more meals re-raises it, not every re-render.
    """
    with get_db() as db:
        items = items if items is not None else _all_items()
        committed = committed_by_item()
        snoozed = {
            row["id"]: row["snooze_estimate"]
            for row in db.execute(
                "SELECT id, snooze_estimate FROM items WHERE snooze_estimate IS NOT NULL"
            ).fetchall()
        }
    out: dict[str, dict] = {}
    for item in items:
        used = committed.get(item["id"], 0.0)
        estimate = max(0.0, item["quantity"] - used)
        low = item["min_quantity"] > 0 and item["quantity"] <= item["min_quantity"]
        floor = snoozed.get(item["id"])
        low_projected = (
            not low
            and item["min_quantity"] > 0
            and estimate <= item["min_quantity"]
            and (floor is None or estimate < floor)
        )
        out[item["id"]] = {
            "estimate": estimate,
            "committed": used,
            "low": low,
            "low_projected": low_projected,
        }
    return out


def snooze(item_id: str, estimate: float) -> None:
    """Dismiss the prompt until the estimate drops below this level."""
    with get_db() as db:
        db.execute(
            "UPDATE items SET snooze_estimate = ? WHERE id = ?", (estimate, item_id)
        )


def _all_items() -> list[dict]:
    from . import repo  # local import: repo imports this module's helpers
    return repo.list_items()
