import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("PANTRY_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app import products, seed  # noqa: E402
from app.db import init_db  # noqa: E402
from app.main import CONTROL_CODES, app  # noqa: E402

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


def test_scan_purchase_restocks_known_item(client):
    salz = next(i for i in _items(client) if i["name"] == "Salz")
    before = salz["quantity"]
    response = client.post("/api/scan/purchase", json={"barcode": salz["barcode"]})
    assert response.status_code == 200
    item = response.json()
    assert item["quantity"] == before + salz["packageSize"]
    assert FakeOFF.calls == 0


def test_scan_purchase_unknown_returns_404(client):
    response = client.post("/api/scan/purchase", json={"barcode": MISS_EAN})
    assert response.status_code == 404
    assert FakeOFF.calls == 0  # enrichment happens via /api/barcode/lookup


def test_scan_empty_zeroes_and_reorders(client):
    client.post("/api/scan/purchase", json={"barcode": "4006434000937"})  # stock up Salz
    response = client.post("/api/scan/empty", json={"barcode": "4006434000937"})
    assert response.status_code == 200
    assert response.json()["quantity"] == 0
    shopping = client.get("/api/shopping-list").json()
    assert any(e["name"] == "Salz" for e in shopping)


def test_control_codes_are_valid_ean13():
    """The sticker page renders these via python-barcode, which rejects wrong
    check digits — keep the constants and the rendered codes in sync."""
    from barcode.ean import EAN13

    for meta in CONTROL_CODES.values():
        assert EAN13(meta["code"]).get_fullcode() == meta["code"]
        assert meta["code"].startswith("20")  # GS1 in-store range
        assert len(meta["code"]) == 13


def test_control_codes_page_renders_svgs(client):
    response = client.get("/print/control-codes")
    assert response.status_code == 200
    body = response.text
    assert "BOUGHT" in body and "EMPTY / TRASH" in body and "CONSUME" in body
    assert body.count("<svg") == 6  # EAN + QR variants
    for meta in CONTROL_CODES.values():
        assert meta["code"] in body


# ------------------------------------------------- multi-barcode items


def test_multiple_barcodes_deduct_from_same_item(client):
    """Eggs from Aldi, REWE and Edeka share one generic stock: any attached
    barcode resolves to the same item."""
    salz = next(i for i in _items(client) if i["name"] == "Salz")
    assert salz["barcodes"] and salz["barcodes"][0] == salz["barcode"]

    # a second vendor's product joins the same item
    response = client.post(
        f"/api/items/{salz['id']}/barcodes", json={"barcode": "4012300999992"})
    assert response.status_code == 200
    assert "4012300999992" in response.json()["barcodes"]

    a = client.post("/api/scan/purchase", json={"barcode": "4006434000937"}).json()
    b = client.post("/api/scan/purchase", json={"barcode": "4012300999992"}).json()
    assert a["id"] == b["id"] == salz["id"]
    body = client.post("/api/barcode/lookup", json={"barcode": "4012300999992"}).json()
    assert body["status"] == "known" and body["item"]["id"] == salz["id"]


def test_add_barcode_rejects_clashes_and_garbage(client):
    milch = next(i for i in _items(client) if i["name"] == "Milch")
    kaffee = next(i for i in _items(client) if i["name"] == "Kaffee")
    # a barcode can only ever point at one item
    response = client.post(
        f"/api/items/{milch['id']}/barcodes", json={"barcode": kaffee["barcode"]})
    assert response.status_code == 409
    assert "Kaffee" in response.json()["detail"]
    assert client.post(f"/api/items/{milch['id']}/barcodes",
                       json={"barcode": "12345"}).status_code == 400
    assert client.post("/api/items/missing/barcodes",
                       json={"barcode": "4012345678901"}).status_code == 404


def test_remove_item_barcode(client):
    salz = next(i for i in _items(client) if i["name"] == "Salz")
    response = client.delete(f"/api/items/{salz['id']}/barcodes/4012300999992")
    assert response.status_code == 200
    assert "4012300999992" not in response.json()["barcodes"]
    # the seeded barcode keeps working
    body = client.post("/api/barcode/lookup", json={"barcode": "4006434000937"}).json()
    assert body["status"] == "known"
    assert client.delete(
        f"/api/items/{salz['id']}/barcodes/0000000000000").status_code == 404


# ------------------------------------------------- scan events + discard


def test_scan_events_record_unknown_scans(client):
    baseline = client.get("/api/scan/events").json()["seq"]
    # known scans record a change ping (for the live UI refresh), never
    # an unknown:* one — those alone drive the review popup
    kaffee = next(i for i in _items(client) if i["name"] == "Kaffee")
    client.post("/api/scan/barcode", json={"barcode": kaffee["barcode"]})
    events = client.get(f"/api/scan/events?since={baseline}").json()["events"]
    assert [e["kind"] for e in events] == ["consume"]
    assert all(not e["kind"].startswith("unknown") for e in events)

    # an unknown scan is visible to popup pollers
    assert client.post("/api/scan/purchase",
                       json={"barcode": "4066600000002"}).status_code == 404
    body = client.get(f"/api/scan/events?since={baseline}").json()
    assert body["events"], "unknown scan should produce an event"
    event = body["events"][-1]
    assert event["barcode"] == "4066600000002"
    assert event["kind"] == "unknown:bought"


def test_discard_pending_barcode(client):
    FakeOFF.responses["4066600000003"] = SALT_PRODUCT
    client.post("/api/barcode/lookup", json={"barcode": "4066600000003"})
    codes = {e["barcode"] for e in client.get("/api/barcode/pending").json()["barcodes"]}
    assert "4066600000003" in codes

    response = client.delete("/api/barcode/pending/4066600000003")
    assert response.status_code == 200
    assert response.json()["discarded"] == "4066600000003"
    codes = {e["barcode"] for e in client.get("/api/barcode/pending").json()["barcodes"]}
    assert "4066600000003" not in codes
    assert client.delete("/api/barcode/pending/4066600000003").status_code == 404


# --------------------------------------- BOUGHT-mode auto item creation


MOCHA_PRODUCT = {
    "status": 1,
    "product": {
        "product_name": "Mocha Testdrink",
        "brands": "Testa",
        "quantity": "500 ml",
        "categories": ["beverages", "coffees", "mochas"],
        "categories_tags": ["en:coffees"],
        "image_small_url": None,
    },
}


def test_bought_scan_auto_creates_stocked_item(client):
    FakeOFF.responses["4066600000021"] = MOCHA_PRODUCT
    response = client.post("/api/scan/purchase", json={"barcode": "4066600000021"})
    assert response.status_code == 200
    item = response.json()
    assert item["name"] == "Mocha Testdrink"
    assert item["unit"] == "l" and item["packageSize"] == 0.5
    assert item["category"] == "Drinks"
    assert item["barcodes"] == ["4066600000021"]
    assert item["quantity"] == 0.5  # starts stocked: one scanned package
    # a second package of the same product just counts up
    second = client.post("/api/scan/purchase", json={"barcode": "4066600000021"})
    assert second.status_code == 200
    assert second.json()["quantity"] == 1.0


def test_bought_scan_attaches_identical_off_names(client):
    """Same OFF product under a second EAN (Aldi/REWE variants): attaches
    the new barcode to the existing item instead of duplicating it."""
    FakeOFF.responses["4066600000022"] = MOCHA_PRODUCT
    response = client.post("/api/scan/purchase", json={"barcode": "4066600000022"})
    assert response.status_code == 200
    item = response.json()
    assert item["name"] == "Mocha Testdrink"
    assert set(item["barcodes"]) == {"4066600000021", "4066600000022"}
    count = sum(1 for i in _items(client) if i["name"] == "Mocha Testdrink")
    assert count == 1


def test_bought_scan_offMiss_stays_unknown(client):
    assert client.post("/api/scan/purchase", json={"barcode": MISS_EAN}).status_code == 404


def test_guess_category():
    assert products.guess_category(["beverages", "colas"]) == "Drinks"
    assert products.guess_category(["dairy", "cheeses"]) == "Dairy"
    assert products.guess_category(["meats", "sausages"]) == "Meat"
    assert products.guess_category(["vegetables", "tomatoes"]) == "Produce"
    assert products.guess_category(["salts", "condiments"]) == "Pantry"
    assert products.guess_category(None) == "Pantry"


def test_off_miss_lands_in_review_queue(client):
    """A barcode Open Food Facts doesn't know still opens the review popup,
    nameless, so the user can name it; assigning then creates a qty item."""
    code = "4066600000004"
    assert FakeOFF.responses.get(code) is None  # a guaranteed OFF miss
    assert client.post("/api/scan/purchase", json={"barcode": code}).status_code == 404

    entries = client.get("/api/barcode/pending").json()["barcodes"]
    entry = next(e for e in entries if e["barcode"] == code)
    assert entry["name"] is None
    assert entry["offMiss"] is True

    item = client.post("/api/barcode/assign", json={
        "barcode": code, "item_name": "Scanfix Unbekannt"}).json()
    assert item["trackingMode"] == "qty"
    codes = {e["barcode"] for e in client.get("/api/barcode/pending").json()["barcodes"]}
    assert code not in codes
    client.delete(f"/api/items/{item['id']}")
