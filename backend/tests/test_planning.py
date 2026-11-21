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

    persons = client.post("/api/plan/persons", json={"name": "Anna"}).json()
    persons = client.post("/api/plan/persons", json={"name": "Ben"}).json()
    anna = next(p for p in persons["persons"] if p["name"] == "Anna")
    ben = next(p for p in persons["persons"] if p["name"] == "Ben")

    # Wednesday: Anna has lunch+dinner, Ben only dinner
    plan = client.post(
        "/api/plan/meals",
        json={"week": week, "day": 2, "meal": "Lunch", "person_ids": [anna["id"]]},
    ).json()
    assert len(plan["meals"]) == 1
    lunch = plan["meals"][0]
    assert [p["name"] for p in lunch["persons"]] == ["Anna"]

    plan = client.post(
        "/api/plan/meals",
        json={"week": week, "day": 2, "meal": "Dinner", "person_ids": [anna["id"]]},
    ).json()
    dinner = next(m for m in plan["meals"] if m["day"] == 2 and m["meal"] == "Dinner")
    plan = client.post(f"/api/plan/meals/{dinner['id']}/persons", json={"person_id": ben["id"]}).json()
    dinner = next(m for m in plan["meals"] if m["id"] == dinner["id"])
    assert sorted(p["name"] for p in dinner["persons"]) == ["Anna", "Ben"]

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
    fill = plan["meals"][0]["fills"][0]
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

    # over-placement is rejected once the batch is used up
    other = client.post("/api/plan/meals", json={"week": week, "day": 4, "meal": "Dinner"}).json()
    friday = next(m for m in other["meals"] if m["day"] == 4)
    leftover = base - placed_expected
    over = client.post(
        f"/api/plan/meals/{friday['id']}/fills",
        json={"prepared_id": batch["id"], "portions": leftover + 1},
    )
    if leftover > 0:
        assert over.status_code == 200
        clamped = over.json()["meals"][0]["fills"][0]
        assert clamped["portions"] == leftover
    else:
        assert over.status_code == 400
    client.delete(f"/api/plan/meals/{friday['id']}")


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

    # cleanup: deleting the dinner meal removes its fills and returns the batch
    plan = client.delete(f"/api/plan/meals/{dinner['id']}")
    assert plan.status_code == 200
    batch_after = next(p for p in plan.json()["prepared"] if p["id"] == batch["id"])
    assert batch_after["placed"] == 0 and batch_after["available"] == base
    client.delete(f"/api/plan/meals/{lunch['id']}")


def test_plan_person_targeted_fills(client):
    week = "2026-02-02"  # a Monday
    plan = client.get(f"/api/plan?week={week}").json()
    persons = plan["persons"]
    assert len(persons) >= 2
    first, second = persons[0], persons[1]

    # a meal with no persons yet
    plan = client.post(
        "/api/plan/meals", json={"week": week, "day": 0, "meal": "Lunch"}
    ).json()
    meal = next(m for m in plan["meals"] if m["day"] == 0)
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
        "/api/plan/meals", json={"week": week, "day": 1, "meal": "Dinner"}
    ).json()
    dinner = next(m for m in plan["meals"] if m["day"] == 1)
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
