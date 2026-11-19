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
    assert response.headers["content-disposition"].endswith(".lemd\"")
    return json.loads(response.text)


# ---------------------------------------------------------------- rendering


def test_item_label_png(client):
    salz = _item(client, "Salz")
    response = client.get(f"/api/labels/item/{salz['id']}/png?tape=24")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(response.content) > 5000


def test_item_label_png_404(client):
    assert client.get("/api/labels/item/missing/png").status_code == 404


def test_label_module_geometry():
    item = {"id": "salz", "name": "Salz", "barcode": "4006434000937"}
    for tape in (12, 24):
        img = labels.item_label(item, "http://192.168.178.96:8321", tape)
        expected_height = int(labels.TAPE_GEOMETRY[tape]["printable"] * labels.PX_PER_MM)
        assert img.height == expected_height
        assert img.width > img.height  # horizontal QR + text layout


def test_control_code_labels_render_all_three():
    for tape in (12, 24):
        rendered = labels.control_code_labels(tape)
        assert len(rendered) == 3
        assert {label for _, label, _ in rendered} == {"BOUGHT", "EMPTY / TRASH", "CONSUME"}


# ------------------------------------------------------------ Epson export


def test_lemd_payload_schema_matches_epson():
    """Structure mirrors LabelGenerator's lemd-generator constants."""
    item = {"id": "salz", "name": "Salz", "barcode": None}
    images = [labels.item_label(item, "http://x", 24)] * 2
    payload = json.loads(labels.generate_lemd(images, 24))

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


def test_control_codes_lemd_download(client):
    payload = _decode_lemd(client.get("/api/labels/control-codes.lemd?tape=24"))
    # 3 control labels + 2 dashed cut lines between them
    assert len(payload["object_list"]) == 5
    assert payload["tape_config"]["width"] == 24


def test_items_lemd_download(client):
    salz = _item(client, "Salz")
    milch = _item(client, "Milch")
    payload = _decode_lemd(
        client.get(f"/api/labels/items.lemd?ids={salz['id']},{milch['id']}&tape=12"))
    assert payload["tape_config"]["width"] == 12
    assert len(payload["object_list"]) == 3  # 2 labels + 1 cut line
    assert client.get("/api/labels/items.lemd?ids=").status_code == 400


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


def test_control_codes_still_importable(client):
    """labels.py is the single source of truth for main.py's sticker page."""
    from app.main import CONTROL_CODES

    assert CONTROL_CODES is labels.CONTROL_CODES
    assert CONTROL_CODES["bought"]["code"] == "2000000000008"
