import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("PANTRY_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app import products, seed  # noqa: E402
from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

# Barcodes absent from the seeded catalog; the fake OFF API below carries
# one REWE-style private-label product and one miss.
SALT_EAN = "4006434000938"
COLA_EAN = "5449000000996"
MISS_EAN = "7649999999999"

SALT_PRODUCT = {
    "status": 1,
    "product": {
        "product_name": "Bad Reichenhaller Jodsalz",
        "brands": "Bad Reichenhaller",
        "quantity": "500 g",
        "categories": ["Salze und Gewürze", "Salze", "Speisesalz"],
        "categories_tags": ["en:salts"],
        "image_small_url": None,
    },
}
COLA_PRODUCT = {
    "status": 1,
    "product": {
        "product_name": "Cola",
        "brands": "REWE Beste Wahl",
        "quantity": "1,5 l",
        "categories": ["Getränke", "Softdrinks", "Cola"],
        "categories_tags": ["en:colas"],
        "image_small_url": None,
    },
}


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeOFF:
    """Stand-in for httpx.get against the OFF-family API, keyed by barcode."""

    responses: dict = {}
    calls: int = 0

    def __call__(self, url, params=None, headers=None, timeout=None):
        type(self).calls += 1
        barcode = url.rsplit("/", 1)[-1].split(".")[0]
        payload = self.responses.get(barcode)
        if payload is None:
            return _Response(404)
        return _Response(200, payload)


@pytest.fixture(scope="module")
def client():
    init_db()
    seed.seed_if_empty()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fake_off(monkeypatch):
    """Hermetic: no OFF-family HTTP traffic; a fresh fixture map per test."""
    FakeOFF.responses = {}
    FakeOFF.calls = 0
    monkeypatch.setattr(products.httpx, "get", FakeOFF(), raising=True)


def _items(client):
    return client.get("/api/items").json()


def test_lookup_known_barcode(client):
    kaffee = next(i for i in _items(client) if i["name"] == "Kaffee")
    response = client.post("/api/barcode/lookup", json={"barcode": kaffee["barcode"]})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "known"
    assert body["item"]["id"] == kaffee["id"]
    # known barcodes never hit the OFF API
    assert FakeOFF.calls == 0


def test_lookup_unknown_fetches_off_and_caches(client):
    FakeOFF.responses[SALT_EAN] = SALT_PRODUCT
    response = client.post("/api/barcode/lookup", json={"barcode": SALT_EAN})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unknown"
    product = body["product"]
    assert product["name"] == "Bad Reichenhaller Jodsalz"
    assert product["brand"] == "Bad Reichenhaller"
    assert product["quantity"] == "500 g"
    assert "Salze" in product["categories"]
    assert [s["name"] for s in body["suggestions"]] == ["Salz"]
    assert body["suggestions"][0]["id"] == "salz"
    assert FakeOFF.calls == 1  # first OFF source answered
    # second lookup is served from the SQLite cache
    cached = client.post("/api/barcode/lookup", json={"barcode": SALT_EAN})
    assert cached.json()["product"]["name"] == "Bad Reichenhaller Jodsalz"
    assert FakeOFF.calls == 1


def test_lookup_not_found_is_cached_negative(client):
    response = client.post("/api/barcode/lookup", json={"barcode": MISS_EAN})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_found"
    assert body["barcode"] == MISS_EAN
    assert FakeOFF.calls == 3  # all three OFF-family sources tried
    again = client.post("/api/barcode/lookup", json={"barcode": MISS_EAN})
    assert again.json()["status"] == "not_found"
    assert FakeOFF.calls == 3


def test_pending_lists_unassigned_with_suggestions(client):
    FakeOFF.responses[SALT_EAN] = SALT_PRODUCT
    client.post("/api/barcode/lookup", json={"barcode": SALT_EAN})
    response = client.get("/api/barcode/pending")
    assert response.status_code == 200
    entries = {e["barcode"]: e for e in response.json()["barcodes"]}
    salt = entries[SALT_EAN]
    assert salt["name"] == "Bad Reichenhaller Jodsalz"
    assert salt["suggestions"][0]["name"] == "Salz"


def test_assign_to_existing_item(client):
    FakeOFF.responses[SALT_EAN] = SALT_PRODUCT
    client.post("/api/barcode/lookup", json={"barcode": SALT_EAN})  # review queue entry
    eier = next(i for i in _items(client) if i["name"] == "Eier")
    response = client.post(
        "/api/barcode/assign", json={"barcode": SALT_EAN, "item_id": eier["id"]}
    )
    assert response.status_code == 200
    assert response.json()["barcode"] == SALT_EAN
    # lookup now reports known, the queue entry is gone
    body = client.post("/api/barcode/lookup", json={"barcode": SALT_EAN}).json()
    assert body["status"] == "known" and body["item"]["id"] == eier["id"]
    pending = {e["barcode"] for e in client.get("/api/barcode/pending").json()["barcodes"]}
    assert SALT_EAN not in pending


def test_assign_creates_new_item_with_package_from_off(client):
    FakeOFF.responses[COLA_EAN] = COLA_PRODUCT
    client.post("/api/barcode/lookup", json={"barcode": COLA_EAN})
    response = client.post(
        "/api/barcode/assign", json={"barcode": COLA_EAN, "item_name": "Cola"}
    )
    assert response.status_code == 200
    item = response.json()
    assert item["id"] and item["name"] == "Cola"
    assert item["barcode"] == COLA_EAN
    # "1,5 l" normalized into OpenPantry's unit spectrum
    assert item["unit"] == "l" and item["packageSize"] == 1.5
    body = client.post("/api/barcode/lookup", json={"barcode": COLA_EAN}).json()
    assert body["status"] == "known"


def test_assign_requires_item_reference(client):
    response = client.post("/api/barcode/assign", json={"barcode": COLA_EAN})
    assert response.status_code == 400


def test_scan_rejects_invalid_barcode(client):
    response = client.post("/api/barcode/lookup", json={"barcode": "123"})
    assert response.status_code == 400
    response = client.post("/api/barcode/lookup", json={"barcode": "abc"})
    assert response.status_code == 400


def test_parse_quantity():
    assert products.parse_quantity("500 g") == (0.5, "kg")
    assert products.parse_quantity("1,5 l") == (1.5, "l")
    assert products.parse_quantity("750 ml") == (0.75, "l")
    assert products.parse_quantity("2 Stück") == (2, "pcs")
    assert products.parse_quantity("") is None
    assert products.parse_quantity("los") is None
