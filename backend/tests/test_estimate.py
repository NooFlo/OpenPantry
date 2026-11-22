"""Stock-estimate projection tests: a planned meal commits its ingredient
need against stock; the Home prompt fires via `low_projected` when the
projection dips under the alarm threshold, while `low` stays the hard
on-disk fact. Uses its own week + names so the shared test DB stays clean
and cleans up after itself."""

import os
import tempfile

os.environ.setdefault("PANTRY_DB", os.path.join(tempfile.mkdtemp(), "test-estimate.db"))

import pytest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app import repo  # noqa: E402

init_db()

from app.main import app  # noqa: E402, F401

WEEK = "2031-05-05"  # far from the weeks other test modules use


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_projection_dips_below_threshold_when_meal_is_planned(client):
    item = client.post("/api/items", json={
        "name": "Projection Eggs", "quantity": 6.0,
        "min_quantity": 5.5, "unit": "pcs", "tracking_mode": "qty",
    }).json()
    assert item["low"] is False  # 6.0 > 5.5 before planning

    recipe = repo.create_recipe(
        "Estimate test omelette", "test", 6,
        [{"raw": "600 g Projection Eggs", "amount": 0.6, "unit": "kg",
          "item_id": item["id"], "tracked": 1}],
        ["_mix"],
    )

    meal = client.post("/api/plan/meals",
                       json={"week": WEEK, "day": 1, "meal": "dinner"}).json()
    dinner = [m for m in meal["meals"] if m["day"] == 1 and m["meal"] == "dinner"][0]
    fill = client.post(f"/api/plan/meals/{dinner['id']}/fills",
                       json={"recipe_id": recipe["id"], "portions": 6})
    assert fill.status_code == 200, fill.text

    listed = {i["name"]: i for i in client.get("/api/items").json()}["Projection Eggs"]
    # planned need: 600 g * 6 filled portions / 6 base = 0.6 -> estimate 5.4
    assert listed["estimate"] == pytest.approx(5.4)
    assert listed["low"] is False  # hard fact untouched: 6.0 > 5.5
    assert listed["lowProjected"] is True  # the plan dips below 5.5 -> prompt

    # the fill removal restores the estimate
    dinner_after = next(m for m in fill.json()["meals"] if m["day"] == 1 and m["meal"] == "dinner")
    client.delete(f"/api/plan/fills/{dinner_after['fills'][0]['id']}")
    listed = {i["name"]: i for i in client.get("/api/items").json()}["Projection Eggs"]
    assert listed["estimate"] == pytest.approx(6.0)
    assert listed["lowProjected"] is False


def test_low_flag_round_trip(client):
    item = client.post("/api/items", json={
        "name": "Estimate Flour", "quantity": 0.0, "min_quantity": 2.0,
        "unit": "kg", "tracking_mode": "qty",
    }).json()
    assert item["low"] is True  # empty <= 2.0

    client.post(f"/api/items/{item['id']}/restock", json={"amount": 3.0})
    listed = {i["name"]: i for i in client.get("/api/items").json()}
    assert listed["Estimate Flour"]["quantity"] == pytest.approx(3.0)
    assert listed["Estimate Flour"]["low"] is False  # 3.0 > 2.0

    client.post(f"/api/items/{item['id']}/consume", json={"amount": 2.5})
    listed = {i["name"]: i for i in client.get("/api/items").json()}
    assert listed["Estimate Flour"]["quantity"] == pytest.approx(0.5)
    assert listed["Estimate Flour"]["low"] is True  # 0.5 <= 2.0 again


def test_binary_items_never_report_fractional(client):
    item = client.post("/api/items", json={
        "name": "Estimate Mustard", "quantity": 1.0, "unit": "pcs",
        "tracking_mode": "binary",
    }).json()
    client.post(f"/api/items/{item['id']}/consume", json={"amount": 1.0})
    listed = {i["name"]: i for i in client.get("/api/items").json()}["Estimate Mustard"]
    assert listed["quantity"] == 0.0
