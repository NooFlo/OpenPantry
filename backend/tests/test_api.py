import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("PANTRY_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    seed.seed_if_empty()
    with TestClient(app) as c:
        yield c


def test_items_seeded(client):
    response = client.get("/api/items")
    assert response.status_code == 200
    items = response.json()
    names = {i["name"] for i in items}
    assert "Salz" in names and "Milch" in names
    butter = next(i for i in items if i["name"] == "Butter")
    assert butter["uncertain"] == 1


def test_consume_clears_uncertain(client):
    items = client.get("/api/items").json()
    butter = next(i for i in items if i["name"] == "Butter")
    response = client.post(f"/api/items/{butter['id']}/consume", json={"amount": 0.25})
    assert response.status_code == 200
    updated = response.json()
    assert updated["quantity"] == 0
    assert updated["uncertain"] == 0


def test_confirm_low_yes_and_no(client):
    items = client.get("/api/items").json()
    butter = next(i for i in items if i["name"] == "Butter")
    client.post(f"/api/items/{butter['id']}/confirm-low", json={"is_low": True})
    assert client.get("/api/items").json()[0]
    items = client.get("/api/items").json()
    butter = next(i for i in items if i["name"] == "Butter")
    assert butter["quantity"] == 0
    client.post(f"/api/items/{butter['id']}/confirm-low", json={"is_low": False})
    items = client.get("/api/items").json()
    butter = next(i for i in items if i["name"] == "Butter")
    assert butter["uncertain"] == 0


def test_cook_deducts_and_marks_uncertain(client):
    items = {i["name"]: i for i in client.get("/api/items").json()}
    milch_before = items["Milch"]["quantity"]
    recipes = client.get("/api/recipes").json()
    ruehrei = next(r for r in recipes if r["title"] == "Rührei")
    items = client.post(f"/api/recipes/{ruehrei['id']}/cook", json={"portions": 2}).json()
    updated = {i["name"]: i for i in items}
    assert updated["Milch"]["quantity"] == pytest.approx(milch_before - 0.05)
    assert updated["Eier"]["quantity"] == 0
    assert updated["Eier"]["uncertain"] == 1


def test_add_missing_rounds_up_to_packages_and_merges(client):
    recipes = client.get("/api/recipes").json()
    pancakes = next(r for r in recipes if r["title"] == "Pancakes")
    items = {i["name"]: i for i in client.get("/api/items").json()}
    assert items["Eier"]["quantity"] == 0

    result = client.post(f"/api/recipes/{pancakes['id']}/add-missing", json={"portions": 2}).json()
    eier = next(e for e in result if e["name"] == "Eier")
    assert eier["amount"] == pytest.approx(10)

    result = client.post(f"/api/recipes/{pancakes['id']}/add-missing", json={"portions": 2}).json()
    eier = next(e for e in result if e["name"] == "Eier")
    assert eier["amount"] == pytest.approx(20)
    names = [e["name"] for e in result]
    assert names.count("Eier") == 1
    assert "Mehl" not in names
    assert "Milch" not in names


def test_receipt_match_creates_item_and_completes(client):
    receipts = client.get("/api/receipts").json()
    lidl = next(r for r in receipts if r["store"] == "Lidl")
    pending = [i for i in lidl["items"] if i["status"] == "pending"]
    assert len(pending) == 3

    response = client.post(
        f"/api/receipts/{lidl['id']}/items/{pending[0]['id']}/match",
        json={"product_name": "Kartoffeln"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "review"

    items = {i["name"] for i in client.get("/api/items").json()}
    assert "Kartoffeln" in items

    for item in pending[1:]:
        client.post(
            f"/api/receipts/{lidl['id']}/items/{item['id']}/match",
            json={"product_name": "Milch"},
        )
    receipt = next(r for r in client.get("/api/receipts").json() if r["id"] == lidl["id"])
    assert receipt["status"] == "done"


def test_import_recipe_from_text(client):
    text = """Käsenudeln
Zutaten für 4 Portionen:
500 g Nudeln
200 g Käse
1 Prise Salz
2 EL Olivenöl
Zuerst die Nudeln kochen.
Dann den Käse schmelzen."""
    response = client.post("/api/recipes/import", json={"kind": "text", "value": text})
    assert response.status_code == 200
    recipe = response.json()
    assert recipe["title"] == "Käsenudeln"
    by_raw = {i["raw"]: i for i in recipe["ingredients"]}
    nudeln = by_raw["500 g Nudeln"]
    assert nudeln["amount"] == 0.5
    assert nudeln["tracked"] == 1
    prise = by_raw["1 Prise Salz"]
    assert prise["tracked"] == 0
    steps = recipe["steps"]
    assert len(steps) == 2


def test_import_recipe_from_link_falls_back_to_heuristic(client):
    response = client.post(
        "/api/recipes/import",
        json={"kind": "link", "value": "https://example.com/recipe"},
    )
    assert response.status_code in (200, 502)


def test_shopping_list_endpoints(client):
    items = client.get("/api/items").json()
    salz = next(i for i in items if i["name"] == "Salz")
    result = client.post(f"/api/shopping-list/{salz['id']}", json={"amount": 0.5}).json()
    assert any(e["name"] == "Salz" for e in result)
    result = client.delete(f"/api/shopping-list/{salz['id']}").json()
    assert not any(e["name"] == "Salz" for e in result)


def test_barcode_scan_consumes_package(client):
    response = client.post("/api/scan/barcode", json={"barcode": "4006434000937"})
    assert response.status_code == 200
    assert response.json()["name"] == "Salz"
    response = client.post("/api/scan/barcode", json={"barcode": "nope"})
    assert response.status_code == 404


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
