import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("PANTRY_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app import repo, seed  # noqa: E402
from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    seed.seed_if_empty()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Keep tests hermetic and deterministic: a locally running Ollama would
    otherwise answer recipe imports and make assertions flaky. Imports in the
    tests always exercise the deterministic schema/heuristic paths."""
    from app import llm
    monkeypatch.setattr(llm, "generate_json", lambda *args, **kwargs: None)


def test_items_seeded(client):
    response = client.get("/api/items")
    assert response.status_code == 200
    items = response.json()
    names = {i["name"] for i in items}
    assert "Salz" in names and "Milch" in names
    butter = next(i for i in items if i["name"] == "Butter")
    assert butter["uncertain"] == 1
    assert butter["trackingMode"] == "binary"  # one unit on record
    eier = next(i for i in items if i["name"] == "Eier")
    assert eier["trackingMode"] == "qty"  # several units on record


def test_consume_clears_uncertain(client):
    items = client.get("/api/items").json()
    butter = next(i for i in items if i["name"] == "Butter")
    response = client.post(f"/api/items/{butter['id']}/consume", json={"amount": 1})
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
    # Milch is binary-tracked: the amount stays on record, the running-low prompt appears
    assert updated["Milch"]["trackingMode"] == "binary"
    assert updated["Milch"]["quantity"] == pytest.approx(milch_before)
    assert updated["Milch"]["uncertain"] == 1
    # Eier are quantity-tracked: exact deduction
    assert updated["Eier"]["quantity"] == 0
    assert updated["Eier"]["uncertain"] == 1


def test_add_missing_rounds_up_to_packages_and_merges(client):
    recipes = client.get("/api/recipes").json()
    pancakes = next(r for r in recipes if r["title"] == "Pancakes")
    items = {i["name"]: i for i in client.get("/api/items").json()}
    assert items["Eier"]["quantity"] == 0
    # cooking Rührei already auto-added the emptied eggs; start from a clean list
    client.delete(f"/api/shopping-list/{items['Eier']['id']}")

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


def test_add_missing_matches_suggestions_and_creates_items(client):
    items = {i["name"]: i for i in client.get("/api/items").json()}
    # Milch is binary by default; switch it to quantity tracking so this test
    # exercises the numeric add-missing path
    client.post(f"/api/items/{items['Milch']['id']}/update", json={"tracking_mode": "qty"})
    recipe = repo.create_recipe(
        "Teriyaki test",
        "pasted",
        2,
        [
            {"raw": "500 g beef mince", "amount": 0.5, "unit": "kg",
             "tracked": True, "suggestion": "beef mince"},
            {"raw": "4 Eier", "amount": 4, "unit": "pcs", "item_id": items["Eier"]["id"], "tracked": True},
            {"raw": "1 l Milch", "amount": 1, "unit": "l", "item_id": items["Milch"]["id"], "tracked": True},
            {"raw": "sea salt, to season"},
        ],
        [],
    )

    before = {e["itemId"]: e["amount"] for e in client.get("/api/shopping-list").json()}
    result = client.post(f"/api/recipes/{recipe['id']}/add-missing", json={"portions": 2}).json()
    by_name = {e["name"]: e["amount"] - before.get(e["itemId"], 0) for e in result}
    # suggestion had no pantry item: new item created with zero stock, full rounded amount added
    assert by_name["beef mince"] == pytest.approx(1)  # 0.5 missing, package size 1 -> 1 kg
    assert by_name["Eier"] == pytest.approx(10)  # 8 needed, 3 in stock -> one pack of 10
    assert by_name["Milch"] == pytest.approx(1)  # 1 needed, 0.4 in stock -> one 1 l pack
    # non-quantifiable and in-stock items are not on the list
    assert "sea salt, to season" not in by_name
    assert "Mehl" not in by_name

    created = next(i for i in client.get("/api/items").json() if i["name"] == "beef mince")
    assert created["quantity"] == 0
    # the suggestion was accepted and persisted on the ingredient
    refreshed = next(r for r in client.get("/api/recipes").json() if r["id"] == recipe["id"])
    beef = next(i for i in refreshed["ingredients"] if "beef mince" in i["raw"].lower())
    assert beef["itemId"] == created["id"]
    assert beef["suggestion"] is None
    # a second call merges into the same entries instead of duplicating;
    # beef mince is binary-tracked, so the single buy is not stacked again
    result = client.post(f"/api/recipes/{recipe['id']}/add-missing", json={"portions": 2}).json()
    names = [e["name"] for e in result]
    assert names.count("beef mince") == 1
    beef_entry = next(e for e in result if e["name"] == "beef mince")
    assert beef_entry["amount"] == pytest.approx(1)


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

    items = {i["name"]: i for i in client.get("/api/items").json()}
    assert "Kartoffeln" in items
    # matching a receipt line is stock in: seeded 1.5 kg + 1 package of 2 kg
    assert items["Kartoffeln"]["quantity"] == pytest.approx(3.5)

    for item in pending[1:]:
        client.post(
            f"/api/receipts/{lidl['id']}/items/{item['id']}/match",
            json={"product_name": "Milch"},
        )
    receipt = next(r for r in client.get("/api/receipts").json() if r["id"] == lidl["id"])
    assert receipt["status"] == "done"
    # several milk packages were entered: the item switched to quantity tracking
    items = {i["name"]: i for i in client.get("/api/items").json()}
    assert items["Milch"]["trackingMode"] == "qty"
    # and stocking up past the alarm took the milk off the shopping list
    assert not any(e["name"] == "Milch" for e in client.get("/api/shopping-list").json())


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
    assert prise["tracked"] == 1
    steps = recipe["steps"]
    assert len(steps) == 2


def test_import_marks_water_untracked(client):
    text = """Brühe
500 ml Wasser
250 g Mehl
Alles verrühren."""
    response = client.post("/api/recipes/import", json={"kind": "text", "value": text})
    assert response.status_code == 200
    recipe = response.json()
    by_raw = {i["raw"]: i for i in recipe["ingredients"]}
    water = by_raw["500 ml Wasser"]
    assert water["tracked"] == 0
    assert water.get("itemId") is None
    assert water.get("suggestion") is None
    mehl = by_raw["250 g Mehl"]
    assert mehl["tracked"] == 1
    assert mehl["itemId"]


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


def test_match_creates_item_with_ingredient_unit(client):
    text = """Testkuchen
300 g Dinkelmehl
1 Prise Salz
Alles vermischen."""
    recipe = client.post("/api/recipes/import", json={"kind": "text", "value": text}).json()
    mehl = next(i for i in recipe["ingredients"] if i["raw"] == "300 g Dinkelmehl")
    assert mehl["suggestion"] == "Dinkelmehl"
    response = client.post(
        f"/api/recipes/{recipe['id']}/ingredients/{mehl['id']}/match",
        json={"item_name": "Weizenmehl Type 405"},
    )
    assert response.status_code == 200
    items = client.get("/api/items").json()
    created = next(i for i in items if i["name"] == "Weizenmehl Type 405")
    assert created["unit"] == "kg"
    matched = response.json()
    ing = next(i for i in matched["ingredients"] if i["id"] == mehl["id"])
    assert ing["amount"] == 0.3
    assert ing["itemId"] == created["id"]


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_settings_defaults_and_update(client):
    settings = client.get("/api/settings").json()
    assert settings["receiptsModel"]["provider"] == "local"
    assert settings["recipesModel"]["provider"] == "local"
    assert settings["cloudKeySet"] is False
    assert "api_key" not in str(settings).lower() or settings.get("cloudApiKey") is None

    response = client.put("/api/settings", json={
        "recipes_model": {"provider": "cloud", "model": "mistral-small-latest"},
        "cloud_api_key": "secret-key-123",
    })
    assert response.status_code == 200
    updated = response.json()
    assert updated["recipesModel"] == {"provider": "cloud", "model": "mistral-small-latest"}
    assert updated["cloudKeySet"] is True
    assert "secret-key-123" not in json.dumps(updated)

    persisted = client.get("/api/settings").json()
    assert persisted["recipesModel"]["provider"] == "cloud"
    assert persisted["cloudKeySet"] is True


def test_settings_invalid_choice_rejected(client):
    response = client.put("/api/settings", json={"receipts_model": {"provider": "magic", "model": "x"}})
    assert response.status_code == 400


def _render(name, amount, unit):
    if not amount:
        return name
    pretty = f"{amount:.2f}".rstrip("0").rstrip(".")
    return f"{name} ({pretty} {unit})" if unit else f"{name} ({pretty})"


def test_ha_push_from_running_low_and_recipe_missing(client, monkeypatch):
    import app.hass as app_hass

    monkeypatch.setattr(app_hass.httpx, "post", _fake_ha_post(calls := []))
    _reset_ha_settings(client)
    calls.clear()

    # the real UI flow: item confirmed low -> appears as "might be running low"
    # with Yes/No -> "Yes" zeroes it -> the user taps Add on the low-stock card
    items = client.get("/api/items").json()
    butter = next(i for i in items if i["name"] == "Butter")
    before = next((e["amount"] for e in client.get("/api/shopping-list").json() if e["name"] == "Butter"), 0.0)
    client.post(f"/api/items/{butter['id']}/confirm-low", json={"is_low": True})
    client.post(f"/api/items/{butter['id']}/confirm-low", json={"is_low": True})
    result = client.post(f"/api/shopping-list/{butter['id']}", json={"amount": 1}).json()
    assert any(e["name"] == "Butter" for e in result)

    expected = {"entity_id": "todo.pantry", "item": _render("Butter", before + 1, butter["unit"])}
    assert any(
        url.endswith("/todo/add_item") and call == expected
        for url, call in calls
    )
    pushed = json.loads(repo.get_setting("ha_pushed") or "[]")
    assert expected["item"] in pushed

    # the recipe flow: "Add missing" merges the missing ingredients into the
    # list and pushes one entry per product
    prev_pushed = set(json.loads(repo.get_setting("ha_pushed") or "[]"))
    calls.clear()
    recipes = client.get("/api/recipes").json()
    pancakes = next(r for r in recipes if r["title"] == "Pancakes")
    result = client.post(f"/api/recipes/{pancakes['id']}/add-missing", json={"portions": 2}).json()
    assert result  # merged entries exist
    names = [e["name"] for e in result]
    assert len(names) == len(set(names))  # merged per product

    # after a successful push the pushed set mirrors the whole pantry list
    pushed = set(json.loads(repo.get_setting("ha_pushed") or "[]"))
    for entry in client.get("/api/shopping-list").json():
        text = _render(entry["name"], entry["amount"], entry["unit"])
        assert text in pushed
    for entry in result:
        text = _render(entry["name"], entry["amount"], entry["unit"])
        # each entry was either freshly pushed or had reached the to-do list
        # before with identical text (the merge case)
        assert text in prev_pushed or any(
            call[1].get("item") == text for call in calls if call[0].endswith("/todo/add_item")
        )


def test_models_endpoint(client):
    response = client.get("/api/models")
    assert response.status_code == 200
    assert "local" in response.json()
    assert "llmAvailable" in response.json()


def _fake_ha_post(calls):
    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json))

        class Response:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"items": []}

        return Response()

    return fake_post


def _reset_ha_settings(client):
    """HA settings persist in the shared test DB; reset them so each test
    starts from a clean, order-independent state."""
    client.put("/api/settings", json={"ha_url": "", "ha_token": "", "ha_entity": ""})
    repo.set_setting("ha_pushed", "")
    client.put("/api/settings", json={
        "ha_url": "http://ha:8123",
        "ha_token": "ha-secret-42",
        "ha_entity": "todo.pantry",
    })


def test_ha_settings_roundtrip(client):
    client.put("/api/settings", json={"ha_url": "", "ha_token": "", "ha_entity": ""})
    repo.set_setting("ha_pushed", "")
    settings = client.get("/api/settings").json()
    assert settings["haKeySet"] is False

    response = client.put("/api/settings", json={
        "ha_url": "http://ha:8123",
        "ha_token": "ha-secret-42",
        "ha_entity": "todo.pantry",
    })
    assert response.status_code == 200
    updated = response.json()
    assert updated["haUrl"] == "http://ha:8123"
    assert updated["haEntity"] == "todo.pantry"
    assert updated["haKeySet"] is True
    assert "ha-secret-42" not in json.dumps(updated)

    persisted = client.get("/api/settings").json()
    assert persisted["haKeySet"] is True
    assert "ha-secret-42" not in json.dumps(persisted)


def test_ha_auto_push_on_add_and_remove(client, monkeypatch):
    import app.hass as app_hass

    monkeypatch.setattr(app_hass.httpx, "post", _fake_ha_post(calls := []))
    _reset_ha_settings(client)

    items = client.get("/api/items").json()
    salz = next(i for i in items if i["name"] == "Salz")
    client.delete(f"/api/shopping-list/{salz['id']}")  # earlier tests may have auto-added it

    result = client.post(f"/api/shopping-list/{salz['id']}", json={"amount": 2}).json()
    assert any(e["name"] == "Salz" for e in result)
    assert calls and calls[-1][0] == "http://ha:8123/api/services/todo/add_item"
    assert calls[-1][1] == {"entity_id": "todo.pantry", "item": "Salz (2 kg)"}

    calls.clear()
    result = client.delete(f"/api/shopping-list/{salz['id']}").json()
    assert not any(e["name"] == "Salz" for e in result)
    assert calls and calls[-1][0] == "http://ha:8123/api/services/todo/remove_item"
    assert calls[-1][1]["item"] == "Salz (2 kg)"


def test_ha_push_endpoint_and_manual_entries_untouched(client, monkeypatch):
    import app.hass as app_hass

    monkeypatch.setattr(app_hass.httpx, "post", _fake_ha_post(calls := []))
    _reset_ha_settings(client)

    items = client.get("/api/items").json()
    reis = next(i for i in items if i["name"] == "Reis")
    client.post(f"/api/shopping-list/{reis['id']}", json={"amount": 1})
    calls.clear()

    response = client.post("/api/shopping-list/push")
    assert response.status_code == 200
    assert response.json()["pushed"] is True
    assert calls == []  # re-added entries are already in Home Assistant

    # entries that were pushed before but no longer wanted get removed from
    # Home Assistant; hand-added lists (never ours) are left untouched
    repo.set_setting("ha_pushed", json.dumps(["Brötchen (5 pcs)"]))
    calls.clear()
    assert client.post("/api/shopping-list/push").json()["pushed"] is True
    assert any(c[0].endswith("/todo/remove_item") and c[1]["item"] == "Brötchen (5 pcs)" for c in calls)
    assert not any(c[1].get("item") == "Brötchen" for c in calls)


def test_recipe_import_persists_meta_and_refresh_rejects_pasted(client):
    response = client.post("/api/recipes/import", json={"kind": "text", "value": "Käsenudeln\n500 g Nudeln\nKochen."})
    assert response.status_code == 200
    recipe = response.json()
    assert recipe["tags"] == []
    assert recipe["imageUrl"] is None
    assert recipe["totalMinutes"] is None
    assert recipe["createdAt"]

    response = client.post(f"/api/recipes/{recipe['id']}/refresh")
    assert response.status_code == 400
    assert response.json()["detail"] == "only recipes imported from a link can be refreshed"


def test_update_item_thresholds(client):
    items = client.get("/api/items").json()
    zwiebeln = next(i for i in items if i["name"] == "Zwiebeln")
    response = client.post(f"/api/items/{zwiebeln['id']}/update", json={"min_quantity": 4, "package_size": 2})
    assert response.status_code == 200
    updated = response.json()
    assert updated["minQuantity"] == 4
    assert updated["packageSize"] == 2

    response = client.post(f"/api/items/{zwiebeln['id']}/update", json={"min_quantity": 0})
    assert response.status_code == 200
    assert response.json()["minQuantity"] == 0  # stepping to 0 disables the alarm

    response = client.post(f"/api/items/{zwiebeln['id']}/update", json={"package_size": 0})
    assert response.status_code == 400
    response = client.post(f"/api/items/{zwiebeln['id']}/update", json={"min_quantity": -1})
    assert response.status_code == 400


def test_consume_to_zero_auto_adds_buy_quantity_once(client):
    items = {i["name"]: i for i in client.get("/api/items").json()}
    milch = items["Milch"]
    client.delete(f"/api/shopping-list/{milch['id']}")
    response = client.post(f"/api/items/{milch['id']}/consume", json={"amount": milch["quantity"]})
    assert response.status_code == 200 and response.json()["quantity"] == 0
    entries = client.get("/api/shopping-list").json()
    entry = next(e for e in entries if e["itemId"] == milch["id"])
    assert entry["amount"] == milch["packageSize"]

    # second consume below zero: no duplicate entry
    client.post(f"/api/items/{milch['id']}/consume", json={"amount": 0.2})
    entries = [e for e in client.get("/api/shopping-list").json() if e["itemId"] == milch["id"]]
    assert len(entries) == 1
    client.delete(f"/api/shopping-list/{milch['id']}")


def test_cook_crossing_threshold_auto_adds(client):
    items = {i["name"]: i for i in client.get("/api/items").json()}
    # Kartoffeln: stock above the alarm; cooking Ofengemuese eventually crosses it
    kartoffeln_id = items["Kartoffeln"]["id"]
    client.post(f"/api/items/{kartoffeln_id}/update", json={"min_quantity": 2})
    client.delete(f"/api/shopping-list/{kartoffeln_id}")
    recipes = client.get("/api/recipes").json()
    ofeng = next(r for r in recipes if r["title"].startswith("Ofengemüse"))
    client.post(f"/api/recipes/{ofeng['id']}/cook", json={"portions": 8})
    entries = [e for e in client.get("/api/shopping-list").json() if e["itemId"] == kartoffeln_id]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["amount"] == items["Kartoffeln"]["packageSize"]
    client.delete(f"/api/shopping-list/{kartoffeln_id}")
    client.post(f"/api/items/{kartoffeln_id}/update", json={"min_quantity": 1})


def test_base_ingredient_name_strips_prep_and_packaging():
    from app.extract import base_ingredient_name

    assert base_ingredient_name("spring onions, white and green parts separated") == "spring onions"
    assert base_ingredient_name("2 Zehen Knoblauch") == "Knoblauch"
    assert base_ingredient_name("1 Bund Petersilie, fein gehackt") == "Petersilie"
    assert base_ingredient_name("1 mittlere Karotte (ca. 80 g)") == "Karotte"
    assert base_ingredient_name("geriebener Gouda") == "Gouda"
    assert base_ingredient_name("mehligkochende Kartoffeln") == "Kartoffeln"
    assert base_ingredient_name("Steamed jasmine rice, to serve") == "jasmine rice"
    # processed products must keep their name
    assert base_ingredient_name("passierte Tomaten") == "passierte Tomaten"
    assert base_ingredient_name("Kirschtomaten") == "Kirschtomaten"
    assert base_ingredient_name("Eier") == "Eier"


def test_needs_name_canonicalization_targets_leftovers():
    from app.extract import needs_name_canonicalization as needs

    assert needs("spring onions separated") is True  # raw line before stripping
    assert needs("3 Zehen Knoblauch, fein gehackt") is False  # deterministic stripper already resolves this
    assert needs("Steamed jasmine rice, to serve") is False  # prep word stripped deterministically
    assert needs("Thumb-sized piece ginger") is True
    assert needs("Nudeln") is False
    assert needs("passierte Tomaten") is False


def test_import_canonicalizes_post_processed_names(client):
    text = """Asian Bowl
Zutaten für 2 Portionen:
200 g Reis
3 spring onions, white and green parts separated
2 Zehen Knoblauch, fein gehackt
Alles anrichten."""
    recipe = client.post("/api/recipes/import", json={"kind": "text", "value": text}).json()
    by_raw = {i["raw"]: i for i in recipe["ingredients"]}
    assert by_raw["3 spring onions, white and green parts separated"]["suggestion"] == "spring onions"
    garlic = by_raw["2 Zehen Knoblauch, fein gehackt"]
    assert garlic["suggestion"] in (None, "Knoblauch")  # matched seeded item or plain name, never a prep hint


def test_import_canonicalization_llm_path(client, monkeypatch):
    from app import llm

    seen = {}

    def fake_canonicalize(names, choice=None, cloud=None):
        seen["names"] = names
        return {"Thumb-sized piece ginger": "Ginger"}

    monkeypatch.setattr(llm, "canonicalize_names", fake_canonicalize)
    text = """Ginger Bowl
Zutaten für 2 Portionen:
200 g Reis
1 Thumb-sized piece ginger, grated
Kochen und servieren."""
    recipe = client.post("/api/recipes/import", json={"kind": "text", "value": text}).json()
    ing = next(i for i in recipe["ingredients"] if i["raw"] == "1 Thumb-sized piece ginger, grated")
    assert seen["names"] == ["Thumb-sized piece ginger"]
    assert ing["suggestion"] == "Ginger"


def test_canonicalize_names_rejects_mistranslations(monkeypatch):
    from app import llm

    monkeypatch.setattr(
        llm, "generate_json", lambda *a, **k: {"names": ["onion", "Karotte"]}
    )
    result = llm.canonicalize_names(["Knoblauch mit Hauch Salz", "mittlere Karotte"])
    # wrong-language outputs fall back to the (already stripped) input
    assert result == {"mittlere Karotte": "Karotte"}


def test_restock_adds_stock_and_clears_uncertain(client):
    item = repo.create_item("Testzwieback", unit="pcs", package_size=2)
    from app.db import get_db
    with get_db() as db:
        db.execute("UPDATE items SET quantity = 1, uncertain = 1 WHERE id = ?", (item["id"],))

    updated = client.post(f"/api/items/{item['id']}/restock", json={"amount": 2}).json()
    assert updated["quantity"] == 3  # one package on record + one added
    assert updated["uncertain"] == 0  # restocking answers the running-low prompt

    response = client.post(f"/api/items/{item['id']}/restock", json={"amount": 0})
    assert response.status_code == 400
    response = client.post("/api/items/doesnotexist/restock", json={"amount": 1})
    assert response.status_code == 404


def test_restock_above_threshold_removes_shopping_list_entry(client):
    item = repo.create_item("Testquark", unit="pcs", package_size=2, tracking_mode="qty")
    from app.db import get_db
    with get_db() as db:
        db.execute("UPDATE items SET quantity = 0, min_quantity = 1 WHERE id = ?", (item["id"],))
        db.execute(
            "INSERT INTO shopping_list (item_id, name, amount, unit) VALUES (?, ?, 2, 'pcs')",
            (item["id"], "Testquark"),
        )

    # one piece arrives: exactly at the alarm level, not above — the entry stays
    client.post(f"/api/items/{item['id']}/restock", json={"amount": 1})
    entries = client.get("/api/shopping-list").json()
    assert any(e["name"] == "Testquark" for e in entries)

    # one more: above the alarm now, the pending buy is removed
    client.post(f"/api/items/{item['id']}/restock", json={"amount": 1})
    entries = client.get("/api/shopping-list").json()
    assert not any(e["name"] == "Testquark" for e in entries)


def test_restock_in_stock_binary_removes_entry(client):
    item = repo.create_item("Testtee2", unit="pcs", package_size=1, tracking_mode="binary")
    from app.db import get_db
    with get_db() as db:
        db.execute(
            "INSERT INTO shopping_list (item_id, name, amount, unit) VALUES (?, ?, 1, 'pcs')",
            (item["id"], "Testtee2"),
        )
    # binary: back in stock at all — the pending buy is removed
    client.post(f"/api/items/{item['id']}/restock", json={"amount": 1})
    entries = client.get("/api/shopping-list").json()
    assert not any(e["name"] == "Testtee2" for e in entries)


def test_update_item_tracking_mode(client):
    items = {i["name"]: i for i in client.get("/api/items").json()}
    reis = items["Reis"]  # seeded binary: under one unit on record
    assert reis["trackingMode"] == "binary"

    response = client.post(f"/api/items/{reis['id']}/update", json={"tracking_mode": "qty"})
    assert response.status_code == 200
    assert response.json()["trackingMode"] == "qty"

    response = client.post(f"/api/items/{reis['id']}/update", json={"tracking_mode": "binary"})
    assert response.status_code == 200
    assert response.json()["trackingMode"] == "binary"

    response = client.post(f"/api/items/{reis['id']}/update", json={"tracking_mode": "grams"})
    assert response.status_code == 400


def test_binary_consume_empties_and_auto_adds(client):
    item = repo.create_item("Testtee", unit="pcs", package_size=2)
    from app.db import get_db
    with get_db() as db:
        db.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item["id"],))

    updated = client.post(f"/api/items/{item['id']}/consume", json={"amount": 0.1}).json()
    assert updated["trackingMode"] == "binary"
    assert updated["quantity"] == 0  # any consumption empties a binary item
    entries = [e for e in client.get("/api/shopping-list").json() if e["itemId"] == item["id"]]
    assert len(entries) == 1
    assert entries[0]["amount"] == 2  # the buy quantity goes on the list once

    client.delete(f"/api/shopping-list/{item['id']}")


def test_binary_add_missing_adds_one_buy_when_out_of_stock(client):
    item = repo.create_item("Testthonig", unit="pcs", package_size=3)
    recipe = repo.create_recipe(
        "Honigbrot test",
        "pasted",
        2,
        [{"raw": "2 EL Honig", "amount": 0.05, "unit": "pcs",
          "item_id": item["id"], "tracked": True}],
        [],
    )
    from app.db import get_db

    # in stock: nothing to buy even though the recipe requires an amount
    with get_db() as db:
        db.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item["id"],))
    result = client.post(f"/api/recipes/{recipe['id']}/add-missing", json={"portions": 2}).json()
    assert not any(e["itemId"] == item["id"] for e in result)

    # out of stock: one buy amount, not the scaled recipe requirement
    client.post(f"/api/items/{item['id']}/consume", json={"amount": 0.1})
    result = client.post(f"/api/recipes/{recipe['id']}/add-missing", json={"portions": 2}).json()
    entries = [e for e in result if e["itemId"] == item["id"]]
    assert len(entries) == 1
    assert entries[0]["amount"] == 3
    client.delete(f"/api/shopping-list/{item['id']}")


def test_delete_item(client):
    item = repo.create_item("Testmarmelade")
    repo.add_to_shopping_list(item["id"], 1)
    recipe = repo.create_recipe(
        "Marmeladenbrot test",
        "pasted",
        2,
        [{"raw": "2 EL Marmelade", "amount": 0.05, "unit": "pcs",
          "item_id": item["id"], "tracked": True}],
        [],
    )

    response = client.delete(f"/api/items/{item['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == item["id"]

    # gone from the inventory and the shopping list; second delete -> 404
    assert repo.get_item(item["id"]) is None
    assert not any(e["itemId"] == item["id"] for e in client.get("/api/shopping-list").json())
    assert client.delete(f"/api/items/{item['id']}").status_code == 404

    # linked recipe ingredients fall back to their raw text
    updated = repo.get_recipe(recipe["id"])
    assert all(ing["item_id"] is None for ing in updated["ingredients"])


def test_empty_tag_zeros_stock_and_adds_to_list(client):
    # a reboxed, quantity-tracked container (like flour) with a tag on it
    item = repo.create_item("Testmehl", unit="kg", package_size=1.5, tracking_mode="qty")
    client.post(f"/api/items/{item['id']}/restock", json={"amount": 3})

    response = client.post(f"/api/items/{item['id']}/empty")
    assert response.status_code == 200 and response.json()["quantity"] == 0
    assert response.json()["uncertain"] == 0

    entries = [e for e in client.get("/api/shopping-list").json() if e["itemId"] == item["id"]]
    assert len(entries) == 1
    assert entries[0]["amount"] == 1.5

    # an already empty container scanned again does not duplicate the buy
    client.post(f"/api/items/{item['id']}/empty")
    entries = [e for e in client.get("/api/shopping-list").json() if e["itemId"] == item["id"]]
    assert len(entries) == 1

    client.delete(f"/api/items/{item['id']}")


def test_tag_landing_pages_act_on_plain_get(client):
    item = repo.create_item("Testzucker", unit="kg", package_size=1.0)
    client.post(f"/api/items/{item['id']}/restock", json={"amount": 2})

    # browser-style GET: buying without touching the stock
    buy = client.get(f"/tag/{item['id']}/buy")
    assert buy.status_code == 200 and "Testzucker" in buy.text
    entries = [e for e in client.get("/api/shopping-list").json() if e["itemId"] == item["id"]]
    assert len(entries) == 1 and entries[0]["amount"] == 1.0
    items = {i["id"]: i for i in client.get("/api/items").json()}
    assert items[item["id"]]["quantity"] == 2  # buying alone leaves stock untouched

    # browser-style GET: emptying zeroes the stock, no duplicate buy
    empty = client.get(f"/tag/{item['id']}/empty")
    assert empty.status_code == 200
    assert next(i for i in client.get("/api/items").json() if i["id"] == item["id"])["quantity"] == 0
    entries = [e for e in client.get("/api/shopping-list").json() if e["itemId"] == item["id"]]
    assert len(entries) == 1

    assert client.get("/tag/does-not-exist/buy").status_code == 404
    client.delete(f"/api/items/{item['id']}")


def test_import_splits_and_or_alternatives(client):
    text = ("Naan-Curry\n"
            "1 Zwiebel\n"
            "500 g Reis\n"
            "**Basmati rice and or naan to serve**")
    recipe = client.post("/api/recipes/import", json={"kind": "text", "value": text}).json()
    by_raw = {i["raw"]: i for i in recipe["ingredients"]}
    assert "Basmati rice" in by_raw
    assert "Naan" in by_raw
    rice, naan = by_raw["Basmati rice"], by_raw["Naan"]
    assert rice["altGroup"] == naan["altGroup"]
    assert rice["selected"] == 0 and naan["selected"] == 0


def test_select_alternative_and_add_missing(client):
    text = ("Testbrot\n"
            "500 g Mehl\n"
            "Basmatireis und/oder Naan\n"
            "Alles verrühren.")
    recipe = client.post("/api/recipes/import", json={"kind": "text", "value": text}).json()
    group = {i["raw"]: i for i in recipe["ingredients"]}
    rice, naan = group["Basmatireis"], group["Naan"]

    # nothing picked yet: the group stays off the shopping list
    before = {e["name"] for e in client.get("/api/shopping-list").json()}
    result = client.post(f"/api/recipes/{recipe['id']}/add-missing", json={"portions": 2}).json()
    assert not ({e["name"] for e in result} - before >= {"Naan"})

    # pick naan
    response = client.post(f"/api/recipes/{recipe['id']}/ingredients/{naan['id']}/select")
    assert response.status_code == 200
    updated = response.json()
    states = {i["raw"]: i["selected"] for i in updated["ingredients"]}
    assert states["Naan"] == 1
    assert states["Basmatireis"] == 0

    result = client.post(f"/api/recipes/{recipe['id']}/add-missing", json={"portions": 2}).json()
    names = [e["name"] for e in result]
    assert "Naan" in names  # the pick is bought (one package)
    assert "Basmatireis" not in names or "Basmatireis" in before  # never both options

    # re-selecting rice flips the single pick
    client.post(f"/api/recipes/{recipe['id']}/ingredients/{rice['id']}/select")
    updated = client.get("/api/recipes").json()
    recipe = next(r for r in updated if r["id"] == recipe["id"])
    states = {i["raw"]: i["selected"] for i in recipe["ingredients"]}
    assert states["Basmatireis"] == 1
    assert states["Naan"] == 0


def test_cook_only_deducts_selected_alternative(client):
    items = {i["name"]: i for i in client.get("/api/items").json()}
    recipe = repo.create_recipe(
        "Alternativ-Test",
        "pasted",
        2,
        [
            {"raw": "Haferflocken", "amount": 0.5, "unit": "kg", "item_id": items["Haferflocken"]["id"],
             "tracked": True, "alt_group": "side-a"},
            {"raw": "Kartoffeln", "amount": 1, "unit": "kg", "item_id": items["Kartoffeln"]["id"],
             "tracked": True, "alt_group": "side-a"},
        ],
        [],
    )
    kartoffeln_before = items["Kartoffeln"]["quantity"]
    hafer_before = items["Haferflocken"]["quantity"]
    # undecided group: nothing is deducted
    repo.cook_recipe(recipe, 2)
    mid = {i["name"]: i for i in repo.list_items()}
    assert mid["Kartoffeln"]["quantity"] == kartoffeln_before
    assert mid["Haferflocken"]["quantity"] == hafer_before
    # pick the potatoes: only they are deducted
    first = next(i for i in recipe["ingredients"] if i["raw"] == "Kartoffeln")
    repo.select_recipe_ingredient(recipe["id"], first["id"])
    recipe = repo.get_recipe(recipe["id"])  # re-fetch: the pick is persisted
    repo.cook_recipe(recipe, 2)
    after = {i["name"]: i for i in repo.list_items()}
    assert after["Kartoffeln"]["quantity"] == pytest.approx(kartoffeln_before - 1)
    assert after["Haferflocken"]["quantity"] == hafer_before


def test_edit_recipe_texts_ingredients_and_steps(client):
    text = ("Editkuchen\n2 Zwiebeln\n300 g Dinkelmehl\n1 Prise Salz\nZuerst vermischen.")
    recipe = client.post("/api/recipes/import", json={"kind": "text", "value": text}).json()
    by_raw = {i["raw"]: i for i in recipe["ingredients"]}
    assert "1 Prise Salz" in by_raw

    response = client.patch(f"/api/recipes/{recipe['id']}", json={
        "title": "Editkuchen XL",
        "base_portions": 6,
        "ingredients": [
            # unchanged line: the pantry match survives
            {"id": by_raw["2 Zwiebeln"]["id"], "raw": "2 Zwiebeln"},
            # changed line: re-parsed and re-matched (400 g -> 0.4 kg)
            {"id": by_raw["300 g Dinkelmehl"]["id"], "raw": "400 g Dinkelmehl"},
            # new line
            {"raw": "2 EL Zucker"},
            # "1 Prise Salz" is dropped
        ],
        "steps": ["New step one", "New step two"],
    })
    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == "Editkuchen XL"
    assert updated["basePortions"] == 6
    assert updated["steps"] == ["New step one", "New step two"]
    raws = [i["raw"] for i in updated["ingredients"]]
    assert "1 Prise Salz" not in raws
    edited_by_raw = {i["raw"]: i for i in updated["ingredients"]}
    # unchanged keeps its item link
    assert edited_by_raw["2 Zwiebeln"]["itemId"]
    # changed line gets the new parsed amount
    assert edited_by_raw["400 g Dinkelmehl"]["amount"] == pytest.approx(0.4)
    assert edited_by_raw["2 EL Zucker"]["amount"] is None

    # persisted across reloads, meta (none here) untouched
    reloaded = next(r for r in client.get("/api/recipes").json() if r["id"] == recipe["id"])
    assert reloaded["title"] == "Editkuchen XL"


def test_edit_recipe_keeps_alternative_group_and_match(client):
    text = ("Testbraten\n1 Zwiebel\nBasmatireis und/oder Naan")
    recipe = client.post("/api/recipes/import", json={"kind": "text", "value": text}).json()
    rice, naan = [i for i in recipe["ingredients"] if i.get("altGroup")]
    client.post(f"/api/recipes/{recipe['id']}/ingredients/{naan['id']}/select")

    updated = client.patch(f"/api/recipes/{recipe['id']}", json={
        "title": "Testbraten 2",
        "ingredients": [
            *[{"id": i["id"], "raw": i["raw"]} for i in recipe["ingredients"]],
        ],
    }).json()
    group = [i for i in updated["ingredients"] if i.get("altGroup")]
    assert len(group) == 2
    assert group[0]["altGroup"] == group[1]["altGroup"]
    # the pick survived the rebuild
    picked = [i for i in group if i["selected"]]
    assert [i["raw"] for i in picked] == ["Naan"]

    # deleting one option leaves a plain single-line ingredient;
    # raw is a required field of each ingredient edit entry
    missing_raw = client.patch(f"/api/recipes/{recipe['id']}", json={
        "ingredients": [{"id": rice["id"]}],
    })
    assert missing_raw.status_code == 422
    updated = client.patch(f"/api/recipes/{recipe['id']}", json={
        "ingredients": [{"id": rice["id"], "raw": rice["raw"]}],
    }).json()
    (plain_ing,) = updated["ingredients"]
    assert plain_ing["altGroup"] is None
    assert plain_ing["raw"] == "Basmatireis"


def test_edit_recipe_validation(client):
    recipes = client.get("/api/recipes").json()
    any_recipe = recipes[0]
    assert client.patch(f"/api/recipes/{any_recipe['id']}", json={"title": "   "}).status_code == 422
    assert client.patch(f"/api/recipes/{any_recipe['id']}", json={"base_portions": 0}).status_code == 422
    assert client.patch("/api/recipes/doesnotexist", json={"title": "x"}).status_code == 404


def test_delete_recipe(client):
    text = "WegDamit\n500 g Mehl\nAlles verrühren."
    recipe = client.post("/api/recipes/import", json={"kind": "text", "value": text}).json()
    response = client.delete(f"/api/recipes/{recipe['id']}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    ids = [r["id"] for r in client.get("/api/recipes").json()]
    assert recipe["id"] not in ids
    assert client.delete(f"/api/recipes/{recipe['id']}").status_code == 404


def test_import_links_step_quantities(client):
    text = ("Zwiebelsuppe\n"
            "2 Zwiebeln\n"
            "500 g Mehl\n"
            "1 Prise Salz\n"
            "Die Zwiebeln anschwitzen.\n"
            "Salz und Mehl einrühren.")
    recipe = client.post("/api/recipes/import", json={"kind": "text", "value": text}).json()
    step_links = recipe["stepIngredients"]
    assert len(step_links) == len(recipe["steps"])
    by_raw = {i["raw"]: i for i in recipe["ingredients"]}
    step0 = step_links[0]
    assert len(step0) == 1  # Zwiebeln mentioned once
    assert step0[0]["ingredientId"] == by_raw["2 Zwiebeln"]["id"]
    assert recipe["steps"][0][step0[0]["start"]:step0[0]["end"]].lower() == "zwiebeln"
    step1 = step_links[1]
    assert [l["ingredientId"] for l in step1] == [by_raw["500 g Mehl"]["id"]]
    # Salz is unquantified (prise): no qty to show, so no link
    assert all(l["ingredientId"] != by_raw["1 Prise Salz"]["id"] for l in step1)


def test_edit_recipe_relinks_step_quantities(client):
    text = ("Mengtest\n500 g Mehl\nDas Mehl langsam und gleichmäßig einrühren.")
    recipe = client.post("/api/recipes/import", json={"kind": "text", "value": text}).json()
    mehl = next(i for i in recipe["ingredients"] if i["raw"] == "500 g Mehl")
    assert recipe["stepIngredients"][0][0]["ingredientId"] == mehl["id"]
    # while steps stay untouched, the (qty) links survive a title edit
    updated = client.patch(f"/api/recipes/{recipe['id']}", json={"title": "Mengtest 2"}).json()
    assert updated["stepIngredients"][0][0]["ingredientId"] == mehl["id"]
    # editing the step text re-derives the links on the new text
    updated = client.patch(f"/api/recipes/{recipe['id']}", json={
        "steps": ["Jetzt das Wasser und das Mehl einrühren."],
    }).json()
    links = updated["stepIngredients"][0]
    assert len(links) == 1
    span = updated["steps"][0][links[0]["start"]:links[0]["end"]]
    assert span.lower() == "mehl"


def _mk(name, unit, quantity, package_size, tracking_mode="qty"):
    item = repo.create_item(name=name, category="Pantry", unit=unit,
                            package_size=package_size,
                            tracking_mode=tracking_mode)
    return repo.restock_item(item["id"], quantity)


def test_package_count_whole_packages_for_volume_items(client):
    """Zitronensaft: 1.5 l in 0.75 l bottles -> 2 packages, not 1.5 l."""
    item = _mk("PackageCount Saft", "l", 1.5, 0.75)
    assert repo.get_item(item["id"])["package_count"] == 2
    # consuming less than half a package doesn't drop the count
    item2 = repo.consume_item(item["id"], 0.2)
    assert item2["quantity"] == 1.3  # exact amount kept internally
    assert item2["package_count"] == 2
    repo.delete_item(item["id"])


def test_package_count_pieces_count_pieces_not_packages(client):
    """pcs items count pieces; packageSize is the buy size, not the display."""
    item = _mk("PackageCount Rollen", "pcs", 2, 10)
    got = repo.get_item(item["id"])
    assert got["quantity"] == 2
    assert got["package_count"] == 2  # 2 rolls, not bundle-of-10 rounding
    repo.delete_item(item["id"])


def test_package_count_binary_items_do_not_count(client):
    item = _mk("PackageCount Folie", "pcs", 1, 1, tracking_mode="binary")
    got = repo.get_item(item["id"])
    assert got["tracking_mode"] == "binary"
    assert got["package_count"] is None
    repo.delete_item(item["id"])
