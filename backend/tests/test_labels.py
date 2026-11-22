import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("PANTRY_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app import labels, seed  # noqa: E402
from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    seed.seed_if_empty()
    with TestClient(app) as c:
        yield c


def _item(client, name):
    return next(i for i in client.get("/api/items").json() if i["name"] == name)


def _decode_lemd(response):
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('.lemd"')
    # a JSON media type would make browsers rename the download to .lemd.json
    # and the Epson app wouldn't recognise the file type
    assert response.headers["content-type"].startswith("application/octet-stream")
    return json.loads(response.text)


# ---------------------------------------------------------------- rendering


def test_control_codes_are_bought_and_trash_only():
    """TRASH *is* consume (deducts one package) — no third sticker."""
    assert set(labels.CONTROL_CODES) == {"bought", "trash"}
    assert labels.CONTROL_CODES["bought"]["code"] == "2000000000008"
    assert labels.CONTROL_CODES["trash"]["code"] == "2000000000015"
    from app.main import CONTROL_CODES

    assert CONTROL_CODES is labels.CONTROL_CODES


def test_control_codes_api_lists_both(client):
    codes = client.get("/api/labels/control-codes").json()
    assert {c["key"] for c in codes} == {"bought", "trash"}
    assert all(c["code"].startswith("20") and c["hint"] for c in codes)


def test_custom_label_module_geometry():
    for tape in (12, 24):
        img = labels.render_custom_label(
            labels.default_elements(tape),
            {"name": "Salz", "category": "Spices", "barcode": "",
             "qr": "http://x/c/salz", "ean": ""},
            50, tape)
        expected_height = int(labels.TAPE_GEOMETRY[tape]["printable"] * labels.PX_PER_MM)
        assert img.height == expected_height
        assert img.width == int(50 * labels.PX_PER_MM)
        assert img.width > img.height  # horizontal label


def test_presets_skip_gridfinity():
    """LabelGenerator's Gridfinity preset is intentionally not carried over."""
    assert set(labels.PRESETS) == {"mm12", "mm24", "storage24"}
    for preset in labels.PRESETS.values():
        assert preset["tape"] in labels.TAPE_GEOMETRY
        assert preset["elements"], "preset must have elements"
        for element in preset["elements"]:
            assert element["field"] in labels.LABEL_FIELDS


def test_render_custom_label_fields():
    elements = [
        {"id": "n", "field": "name", "x": 1, "y": 1, "w": 20, "h": 6,
         "fontSizePt": 20, "text": ""},
        {"id": "t", "field": "text", "x": 1, "y": 8, "w": 20, "h": 4,
         "fontSizePt": 8, "text": "hint"},
        {"id": "q", "field": "qr", "x": 40, "y": 1, "w": 8, "h": 8,
         "fontSizePt": 0, "text": ""},
        {"id": "e", "field": "ean", "x": 40, "y": 10, "w": 8, "h": 6,
         "fontSizePt": 0, "text": ""},
    ]
    data = {"name": "Salz", "category": "Spices", "barcode": "4006434000937",
            "qr": "http://x/c/salz", "ean": "4006434000937"}
    img = labels.render_custom_label(elements, data, 50, 24)
    assert img.size == (int(50 * labels.PX_PER_MM),
                        int(labels.TAPE_GEOMETRY[24]["printable"] * labels.PX_PER_MM))
    qr_variant = labels.render_custom_label(elements, data, 50, 24, qr_instead_of_ean=True)
    assert qr_variant.size == img.size


def test_render_skips_unresolvable_fields():
    """An empty value (no barcode on the item) renders nothing for its box."""
    elements = [{"id": "e", "field": "ean", "x": 1, "y": 1, "w": 10, "h": 6,
                 "fontSizePt": 0, "text": ""}]
    img = labels.render_custom_label(elements, {"qr": "", "ean": ""}, 50, 24)
    assert img.size[0] > 0  # does not raise


# ------------------------------------------------------ item design lifecycle


def test_item_custom_label_roundtrip(client):
    salz = _item(client, "Salz")
    assert client.get(f"/api/labels/custom/item/{salz['id']}").status_code == 404

    # checkbox flow: PUT without elements starts from the tape's default preset
    created = client.put(f"/api/labels/custom/item/{salz['id']}",
                         json={"widthMm": 50, "tape": 24}).json()
    assert created["tape"] == 24
    assert created["widthMm"] == 50
    assert len(created["elements"]) >= 2
    assert {el["field"] for el in created["elements"]} == {"name", "qr"}
    assert created["createdAt"]

    # list shows the item as having a custom label
    listing = client.get("/api/labels/custom").json()
    assert any(entry["itemId"] == salz["id"] for entry in listing)

    # editor save: full element list replaces the design, creation date keeps
    edited = client.put(
        f"/api/labels/custom/item/{salz['id']}",
        json={"tape": 12, "widthMm": 60, "elements": [
            {"id": "n", "field": "name", "x": 1, "y": 0.5, "w": 40, "h": 8,
             "fontSizePt": 16, "text": ""},
            {"id": "c", "field": "category", "x": 1, "y": None, "w": "wide",
             "h": 3, "fontSizePt": 8, "text": ""},
        ]}).json()
    assert edited["tape"] == 12
    assert edited["widthMm"] == 60
    # junk values are cleaned up, not stored raw
    cleaned = {el["id"]: el for el in edited["elements"]}
    assert cleaned["c"]["y"] == 0
    assert cleaned["c"]["w"] == 10

    # preview PNG renders the unsaved work-in-progress as well
    preview = client.post(
        f"/api/labels/preview/item/{salz['id']}",
        json={"tape": 24, "widthMm": 50, "elements": [
            {"id": "n", "field": "name", "x": 1, "y": 1, "w": 30, "h": 10,
             "fontSizePt": 30, "text": ""}]})
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content[:8] == b"\x89PNG\r\n\x1a\n"

    # saved-design PNG + delete (unchecking "Create custom label")
    png = client.get(f"/api/labels/custom/item/{salz['id']}/png")
    assert png.status_code == 200
    assert png.headers["content-type"] == "image/png"
    assert client.delete(f"/api/labels/custom/item/{salz['id']}").json() == {"deleted": True}
    assert client.get(f"/api/labels/custom/item/{salz['id']}").status_code == 404


def test_item_custom_label_unknown_item(client):
    assert client.put("/api/labels/custom/item/missing",
                      json={"widthMm": 50, "tape": 24}).status_code == 404
    assert client.get("/api/labels/custom/item/missing/png").status_code == 404


def test_custom_labels_sorted_by_most_recently_added(client):
    listing = client.get("/api/labels/custom").json()
    eier, milch = _item(client, "Eier"), _item(client, "Milch")
    client.put(f"/api/labels/custom/item/{eier['id']}", json={"widthMm": 50, "tape": 24})
    client.put(f"/api/labels/custom/item/{milch['id']}", json={"widthMm": 50, "tape": 24})
    client.delete(f"/api/labels/custom/item/{eier['id']}")
    client.put(f"/api/labels/custom/item/{eier['id']}", json={"widthMm": 50, "tape": 24})
    # Eier's design was created last -> first in the list despite name order
    listing = client.get("/api/labels/custom").json()
    ids = [entry["itemId"] for entry in listing]
    assert ids.index(eier["id"]) < ids.index(milch["id"])
    client.delete(f"/api/labels/custom/item/{milch['id']}")
    client.delete(f"/api/labels/custom/item/{eier['id']}")


def test_custom_labels_lemd_strip(client):
    salz, milch = _item(client, "Salz"), _item(client, "Milch")
    for item in (salz, milch):
        client.put(f"/api/labels/custom/item/{item['id']}", json={"widthMm": 50, "tape": 12})
    try:
        payload = _decode_lemd(
            client.get(f"/api/labels/custom.lemd?ids={salz['id']},{milch['id']}&tape=12"))
        assert payload["tape_config"]["width"] == 12
        assert len(payload["object_list"]) == 3  # 2 labels + 1 dashed cut line
        # items without a design don't break the batch -> 404 names them
        assert client.get("/api/labels/custom.lemd?ids=missing").status_code == 404
        assert client.get("/api/labels/custom.lemd?ids=").status_code == 400
    finally:
        for item in (salz, milch):
            client.delete(f"/api/labels/custom/item/{item['id']}")


# ------------------------------------------------------------ control designs


def test_control_design_default_falls_back(client):
    fallback = client.get("/api/labels/custom/control/bought").json()
    assert fallback["control"] == "bought"
    assert {el["field"] for el in fallback["elements"]} == {"name", "ean"}
    assert client.get("/api/labels/custom/control/nope").status_code == 404


def test_control_design_save_and_render(client):
    design = client.put(
        "/api/labels/custom/control/trash",
        json={"tape": 24, "widthMm": 55, "elements": [
            {"id": "cap", "field": "name", "x": 1, "y": 1, "w": 25, "h": 7,
             "fontSizePt": 16, "text": ""},
            {"id": "code", "field": "ean", "x": 1, "y": 9, "w": 50, "h": 8,
             "fontSizePt": 0, "text": ""},
        ]}).json()
    assert design["control"] == "trash"
    saved = client.get("/api/labels/custom/control/trash").json()
    assert len(saved["elements"]) == 2
    png = client.get("/api/labels/custom/control/trash/png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    preview = client.post("/api/labels/preview/control/bought",
                          json={"tape": 24, "widthMm": 50, "elements": [
                              {"id": "cap", "field": "name", "x": 1, "y": 1,
                               "w": 20, "h": 6, "fontSizePt": 14, "text": ""}]})
    assert preview.status_code == 200
    # clean up so later assertions see the default sticker design again
    from app import repo

    with repo.get_db() as db:
        db.execute("DELETE FROM custom_labels WHERE control = 'trash'")


def test_control_codes_lemd_download(client):
    payload = _decode_lemd(client.get("/api/labels/control-codes.lemd?tape=24"))
    # 2 control labels + 1 dashed cut line between them
    assert len(payload["object_list"]) == 3
    assert payload["tape_config"]["width"] == 24


def test_control_codes_lemd_qr_format(client):
    payload = _decode_lemd(client.get("/api/labels/control-codes.lemd?tape=24&format=qr"))
    assert len(payload["object_list"]) == 3


# ------------------------------------------------------------ Epson export


def test_lemd_payload_schema_matches_epson():
    """Structure mirrors LabelGenerator's lemd-generator constants."""
    image = labels.render_custom_label(
        labels.default_elements(24),
        {"name": "Salz", "category": "", "barcode": "", "qr": "http://x/c/salz",
         "ean": ""}, 50, 24)
    payload = json.loads(labels.generate_lemd([image] * 2, 24))

    assert payload["version"] == "1.2.0"
    assert payload["signature"] == "Epson Label Editor mobile layout data"
    tape = payload["tape_config"]
    assert tape == {"width": 24, "auto_length": True, "margin": 1,
                    "length": tape["length"], "kind": "tape"}
    assert tape["length"] >= 3
    # two labels + one dashed cut line
    objects = payload["object_list"]
    assert len(objects) == 3
    image_objects = [o for o in objects if o["object_type"] == "image"]
    assert all(o["image"]["dither"] == "threshold" for o in image_objects)
    assert all(o["image"]["source"].startswith("/9j/") for o in image_objects)  # JPEG b64
    # LabelGenerator printable-area constants
    assert objects[0]["block_info"]["points"][0]["y"] == 2.95  # 24mm top offset
    assert objects[0]["block_info"]["points"][1]["y"] == 2.95 + 18.1


# ------------------------------------------------------------ QR base URL


def test_label_base_url_setting_wins(client):
    """A configured `label_base_url` is what QRs encode — regardless of how
    the render request arrived (localhost, LAN IP, tunnel)."""
    from app import main as main_module

    client.put("/api/settings", json={"label_base_url": "http://192.168.178.96:8321"})
    assert client.get("/api/settings").json()["labelBaseUrl"] == "http://192.168.178.96:8321"
    class FakeUrl:
        port, scheme = 8321, "http"

    class FakeRequest:
        url = FakeUrl()
        base_url = "http://localhost:8321/"

    assert main_module._label_base_url(FakeRequest()) == "http://192.168.178.96:8321"
    # invalid URLs are rejected
    assert client.put("/api/settings", json={"label_base_url": "not a url"}).status_code == 400
    # clearing the setting falls through to auto-detect / request origin
    assert client.put("/api/settings", json={"label_base_url": ""}).json()["labelBaseUrl"] == ""
    assert main_module._label_base_url(FakeRequest()) != "http://192.168.178.96:8321"


def test_label_base_url_auto_detects_lan_ip(client, monkeypatch):
    from app import main as main_module

    class FakeUrl:
        port, scheme = 8321, "http"

    class FakeRequest:
        url = FakeUrl()
        base_url = "http://testserver/"

    monkeypatch.setattr(main_module, "_lan_ip", lambda: "10.0.0.55")
    assert main_module._label_base_url(FakeRequest()) == "http://10.0.0.55:8321"
    # no LAN route -> fall back to the request's own origin
    monkeypatch.setattr(main_module, "_lan_ip", lambda: None)
    assert main_module._label_base_url(FakeRequest()) == "http://testserver"


def test_lan_ip_returns_routable_address(client):
    """Best-effort check where the network allows it; skipped when the test
    host has no outbound route (sandboxed CI)."""
    from app import main as main_module

    ip = main_module._lan_ip()
    if ip is None:
        import pytest

        pytest.skip("no outbound route")
    assert not ip.startswith("127.")


# ------------------------------------------------------------ scanning


def test_scan_empty_endpoint_now_consumes(client):
    """TRASH *is* consume: the legacy empty-scan route deducts one package
    instead of zeroing the item (the bridge should point trash mode at
    /api/scan/barcode; this stays only as a compatibility alias)."""
    probe = client.post(
        "/api/barcode/assign",
        json={"barcode": "4012345678902", "item_name": "Trashprobe"}).json()
    client.post("/api/scan/purchase", json={"barcode": "4012345678902"})
    client.post("/api/scan/purchase", json={"barcode": "4012345678902"})
    before = next(i for i in client.get("/api/items").json()
                  if i["name"] == "Trashprobe")["quantity"]
    response = client.post("/api/scan/empty", json={"barcode": "4012345678902"})
    assert response.status_code == 200
    after = response.json()["quantity"]
    assert before - after == _package_size(client, "Trashprobe")
    client.delete(f"/api/items/{probe['id']}")


def _package_size(client, name):
    return next(i for i in client.get("/api/items").json()
                if i["name"] == name)["packageSize"]


# ------------------------------------------------------- barcode adjustment


def test_update_item_barcode(client):
    eier = _item(client, "Eier")
    old_barcode = eier.get("barcode")
    try:
        response = client.post(
            f"/api/items/{eier['id']}/update",
            json={"barcode": "4012300012345"})
        assert response.status_code == 200
        assert response.json()["barcode"] == "4012300012345"
    finally:
        client.post(f"/api/items/{eier['id']}/update", json={"barcode": old_barcode or ""})


def test_update_item_barcode_validates(client):
    eier = _item(client, "Eier")
    assert client.post(f"/api/items/{eier['id']}/update",
                       json={"barcode": "abc123"}).status_code == 400
    assert client.post(f"/api/items/{eier['id']}/update",
                       json={"barcode": "12345"}).status_code == 400


def test_update_item_barcode_rejects_duplicate(client):
    kaffee = _item(client, "Kaffee")
    milch = _item(client, "Milch")
    response = client.post(
        f"/api/items/{milch['id']}/update", json={"barcode": kaffee["barcode"]})
    assert response.status_code == 409
    assert "Kaffee" in response.json()["detail"]


def test_clear_item_barcode(client):
    response = client.post(
        f"/api/items/{_item(client, 'Eier')['id']}/update", json={"barcode": ""})
    assert response.status_code == 200
    assert response.json()["barcode"] is None


def test_scan_item_endpoint(client):
    """Item-label QR typed by the wedge (…/c/<id>) consumes one package."""
    probe = client.post(
        "/api/barcode/assign",
        json={"barcode": "4012345678902", "item_name": "Scanprobe"}).json()
    assert client.post("/api/scan/purchase",
                       json={"barcode": "4012345678902"}).status_code == 200
    before = _item(client, "Scanprobe")["quantity"]
    response = client.post("/api/scan/item", json={"item_id": probe["id"]})
    assert response.status_code == 200
    consumed = response.json()
    assert consumed["name"] == "Scanprobe"
    assert consumed["quantity"] < before
    assert client.post("/api/scan/item", json={"item_id": "missing"}).status_code == 404
    client.delete(f"/api/items/{probe['id']}")
