import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("PANTRY_DB", os.path.join(tempfile.mkdtemp(), "test-plan.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app import seed  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    seed.seed_if_empty()
    with TestClient(app) as c:
        yield c


def test_planning_setting_toggle(client):
    assert client.get("/api/settings").json()["planningEnabled"] is True
    put = client.put(
        "/api/settings", json={"planning_enabled": False}
    )
    assert put.status_code == 200
    assert put.json()["planningEnabled"] is False
    client.put("/api/settings", json={"planning_enabled": True})
    assert client.get("/api/settings").json()["planningEnabled"] is True


def test_planning_gates_off(client):
    client.put("/api/settings", json={"planning_enabled": False})
    assert client.get("/api/plan?week=2026-01-05").status_code == 200
    client.put("/api/settings", json={"planning_enabled": True})


def test_plan_full_flow(client):
    week = "2026-01-05"  # a Monday
    plan = client.get(f"/api/plan?week={week}").json()
    assert plan["weekStart"] == week

    # fixed slots: every day carries Lunch then Dinner, aligned across days
    days: dict[int, list[str]] = {}
    for m in plan["meals"]:
        days.setdefault(m["day"], []).append(m["meal"])
    assert len(plan["meals"]) == 14
    for day in range(7):
        assert days[day][:2] == ["Lunch", "Dinner"]

    # persons attach to every slot as soon as they exist
    client.post("/api/plan/persons", json={"name": "Anna"})
    persons = client.post("/api/plan/persons", json={"name": "Ben"}).json()["persons"]
    anna = next(p for p in persons if p["name"] == "Anna")
    ben = next(p for p in persons if p["name"] == "Ben")
    plan = client.get(f"/api/plan?week={week}").json()
    assert all(
        sorted(p["name"] for p in m["persons"]) == ["Anna", "Ben"]
        for m in plan["meals"]
    )

    # re-adding a fixed slot reuses it — no duplicates
    plan = client.post(
        "/api/plan/meals",
        json={"week": week, "day": 2, "meal": "Lunch", "person_ids": [anna["id"]]},
    ).json()
    lunches = [m for m in plan["meals"] if m["day"] == 2 and m["meal"] == "Lunch"]
    assert len(lunches) == 1
    lunch = lunches[0]
    dinner = next(m for m in plan["meals"] if m["day"] == 2 and m["meal"] == "Dinner")

    recipes = client.get("/api/recipes").json()
    recipe = next(r for r in recipes if r["ingredients"] and r["basePortions"])
    base = recipe["basePortions"]
    assert base >= 2
    # effective ingredients: outside and/or groups, or the picked option
    effective = [
        i for i in recipe["ingredients"]
        if i.get("itemId") and (not i.get("altGroup") or i.get("selected"))
    ]

    # recipe drop with portions + food prep multiplier
    plan = client.post(
        f"/api/plan/meals/{lunch['id']}/fills",
        json={"recipe_id": recipe["id"], "portions": 2, "prep_multiplier": 1},
    ).json()
    lunch = next(m for m in plan["meals"] if m["id"] == lunch["id"])
    fill = lunch["fills"][0]
    assert fill["portions"] == 2 and fill["prepMultiplier"] == 1
    prepared = plan["prepared"]
    assert len(prepared) == 1
    batch = prepared[0]
    assert batch["recipeId"] == recipe["id"]
    assert batch["portions"] == base  # 1 food-prep multiplier x base portions
    assert batch["available"] == base

    # placing the prepared batch consumes availability
    plan = client.post(
        f"/api/plan/meals/{dinner['id']}/fills",
        json={"prepared_id": batch["id"], "portions": 3},
    ).json()
    batch_now = next(p for p in plan["prepared"] if p["id"] == batch["id"])
    placed_expected = min(3, base)
    assert batch_now["placed"] == placed_expected
    assert batch_now["available"] == base - placed_expected

    # every day owns a Dinner slot — Friday's is ready for over-placement
    plan = client.get(f"/api/plan?week={week}").json()
    friday_dinner = next(m for m in plan["meals"] if m["day"] == 4 and m["meal"] == "Dinner")
    leftover = base - placed_expected
    over = client.post(
        f"/api/plan/meals/{friday_dinner['id']}/fills",
        json={"prepared_id": batch["id"], "portions": leftover + 1},
    )
    if leftover > 0:
        assert over.status_code == 200
        clamped = next(
            m for m in over.json()["meals"] if m["id"] == friday_dinner["id"]
        )["fills"][0]
        assert clamped["portions"] == leftover
    else:
        assert over.status_code == 400

    # fixed slots cannot be deleted...
    refused = client.delete(f"/api/plan/meals/{friday_dinner['id']}")
    assert refused.status_code == 400
    # ...but removing their fills frees the batch again
    if leftover > 0:
        del_fill = next(
            m for m in over.json()["meals"] if m["id"] == friday_dinner["id"]
        )["fills"][0]
        plan = client.delete(f"/api/plan/fills/{del_fill['id']}").json()
        batch_after = next(p for p in plan["prepared"] if p["id"] == batch["id"])
        assert batch_after["placed"] == placed_expected

    # ...custom meals can still be added and removed
    plan = client.post(
        "/api/plan/meals", json={"week": week, "day": 4, "meal": "Snack"}
    ).json()
    snack = next(m for m in plan["meals"] if m["meal"] == "Snack")
    plan = client.delete(f"/api/plan/meals/{snack['id']}").json()
    assert not [m for m in plan["meals"] if m["meal"] == "Snack"]

    # manual prepared meal (frozen leftovers)
    plan = client.post("/api/plan/prepared", json={"name": "Frozen chili", "portions": 2}).json()
    manual = next(p for p in plan["prepared"] if p["name"] == "Frozen chili")
    assert manual["manual"] is True and manual["available"] == 2

    # a fill needs exactly one of recipe/prepared
    bad = client.post(
        f"/api/plan/meals/{lunch['id']}/fills", json={"portions": 1}
    )
    assert bad.status_code == 400

    # week shopping list scales with portions + prep: zero out one mapped
    # ingredient so its requirement is guaranteed to be missing
    item_id = effective[0]["itemId"]
    assert item_id
    items = {i["id"]: i for i in client.get("/api/items").json()}
    client.post(f"/api/items/{item_id}/consume", json={"amount": items[item_id]["quantity"]})
    list_response = client.get(f"/api/plan/{week}/shopping-list").json()
    entry = next(e for e in list_response if e["itemId"] == item_id)
    assert entry["amount"] > 0 and entry["unit"]
    unmapped = [e for e in list_response if e["itemId"] is None]
    assert all(e["amount"] > 0 for e in unmapped)

    before = len(client.get("/api/shopping-list").json())
    pushed_list = client.post(f"/api/plan/{week}/shopping-list/push")
    assert pushed_list.status_code == 200
    assert len(pushed_list.json()) >= before

    # cleanup: with fixed slots the fills are deleted, not the meals
    plan = client.get(f"/api/plan?week={week}").json()
    for meal in plan["meals"]:
        if meal["day"] == 2:
            for fill in meal["fills"]:
                plan = client.delete(f"/api/plan/fills/{fill['id']}").json()
    batch_final = next(p for p in plan["prepared"] if p["id"] == batch["id"])
    assert batch_final["placed"] == 0 and batch_final["available"] == base


def test_plan_person_targeted_fills(client):
    week = "2026-02-02"  # a Monday
    plan = client.get(f"/api/plan?week={week}").json()
    persons = plan["persons"]
    assert len(persons) >= 2
    first, second = persons[0], persons[1]

    # a meal with no persons yet
    plan = client.post(
        "/api/plan/meals", json={"week": week, "day": 0, "meal": "Brunch"}
    ).json()
    meal = next(m for m in plan["meals"] if m["day"] == 0 and m["meal"] == "Brunch")
    assert meal["persons"] == []

    # prepared batch with two portions: whole-field drop auto-attaches both
    # persons and places one portion per person
    plan = client.post(
        "/api/plan/prepared", json={"name": "Goulash", "portions": 3}
    ).json()
    goulash = next(p for p in plan["prepared"] if p["name"] == "Goulash")
    plan = client.post(
        f"/api/plan/meals/{meal['id']}/fills",
        json={
            "prepared_id": goulash["id"],
            "portions": 2,
            "person_ids": [first["id"], second["id"]],
        },
    ).json()
    meal = next(m for m in plan["meals"] if m["id"] == meal["id"])
    assert sorted(p["id"] for p in meal["persons"]) == sorted(
        [first["id"], second["id"]]
    )
    assert len(meal["fills"]) == 1
    assert meal["fills"][0]["portions"] == 2
    assert meal["fills"][0]["personId"] is None

    # a second meal: dropping onto one person's half tags the fill and
    # attaches just that person
    plan = client.post(
        "/api/plan/meals", json={"week": week, "day": 1, "meal": "Late snack"}
    ).json()
    dinner = next(m for m in plan["meals"] if m["day"] == 1 and m["meal"] == "Late snack")
    plan = client.post(
        f"/api/plan/meals/{dinner['id']}/fills",
        json={"prepared_id": goulash["id"], "person_id": first["id"]},
    ).json()
    dinner = next(m for m in plan["meals"] if m["id"] == dinner["id"])
    assert [p["id"] for p in dinner["persons"]] == [first["id"]]
    fill = dinner["fills"][0]
    assert fill["portions"] == 1
    assert fill["personId"] == first["id"]
    assert fill["personName"] == first["name"]
    # both portions of the batch are placed now
    batch = next(p for p in plan["prepared"] if p["id"] == goulash["id"])
    assert batch["available"] == 0 and batch["placed"] == 3

    # deleting the second meal frees its portion again
    plan = client.delete(f"/api/plan/meals/{dinner['id']}").json()
    batch = next(p for p in plan["prepared"] if p["id"] == goulash["id"])
    assert batch["available"] == 1
    client.delete(f"/api/plan/meals/{meal['id']}")
    client.delete(f"/api/plan/prepared/{goulash['id']}")
