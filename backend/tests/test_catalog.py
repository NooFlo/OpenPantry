"""Concept-catalog tests: the matching cascade, substitution tiers, the
import junk rules and the standardize job. All deterministic — no LLM."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("PANTRY_DB", os.path.join(tempfile.mkdtemp(), "catalog-test.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app import catalog, repo, seed  # noqa: E402
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
    from app import llm
    monkeypatch.setattr(llm, "generate_json", lambda *args, **kwargs: None)


# ---------------------------------------------------------------- resolve
def test_resolve_bilingual_and_traps():
    assert catalog.resolve("cinnamon sticks")[0] == "cinnamon_stick"
    assert catalog.resolve("Zimtstangen")[0] == "cinnamon_stick"
    assert catalog.resolve("peanut oil")[0] == "peanut_oil"
    assert catalog.resolve("Erdnussöl")[0] == "peanut_oil"
    assert catalog.resolve("whole milk")[0] == "milk"
    # Kümmel vs Kreuzkümmel is decided by data, never by fuzz
    assert catalog.resolve("caraway seeds")[0] == "caraway"
    assert catalog.resolve("Kreuzkümmel")[0] == "cumin"
    assert catalog.resolve("ground cumin")[0] == "cumin"
    # ...and the fuzzy layer must never blur the pair either
    res = catalog.resolve_for_stock("kümmel", items=[])
    assert res["kind"] in ("buy", "unknown")


def test_resolve_normalization_tailings():
    assert catalog.resolve("ice cream, to serve")[0] == "ice_cream"
    assert catalog.resolve("Eier (Größe M)")[0] == "eggs"
    assert catalog.resolve("etwas Butter für die Formen")[0] == "butter"
    assert catalog.resolve("0.5 bunch coriander (cilantro)")[0] == "coriander_fresh"
    assert catalog.resolve("juice of 2 limes and zest")[0] == "lime_juice"
    assert catalog.resolve("boiling water")[0] == "water"


def test_item_resolution_by_containment():
    assert catalog.resolve_item_concept(
        {"name": "Bio Natives Olivenöl Extra"}) == "olive_oil"
    assert catalog.resolve_item_concept(
        {"name": "5 Gewürtz Mischung - Fenchel, Zimt, Nelken, Szechuan Pfeffer, Sternanis"}
    ) == "five_spice"
    assert catalog.resolve_item_concept({"name": "Unheardof Gadget"}) is None


# ------------------------------------------------------- cascade tiers
def _items(*specs):
    out = []
    for i, name in enumerate(specs):
        out.append({"id": f"i{i}", "name": name, "quantity": 1})
    return out


def test_cascade_identity_variant_sibling():
    items = _items("Kardamom Saat", "Paprika edelsüss", "Passierte Tomaten")
    res = catalog.resolve_for_stock("green cardamom pods", items)
    assert res["kind"] == "identity"
    assert res["item_name"] == "Kardamom Saat"
    assert res["note"]  # form-drift hint for the stocked form
    res = catalog.resolve_for_stock("smoked paprika", items)
    assert res["kind"] == "sibling"
    assert res["item_name"] == "Paprika edelsüss"
    assert res["note"]
    res = catalog.resolve_for_stock("tomato paste", items)
    assert res["kind"] == "sibling"  # tomato paste ≠ passata: concentrate note


def test_cascade_in_blend_only_for_spices():
    items = _items("Cajun", "5 Gewürtz Mischung - Fenchel, Zimt, Nelken, Szechuan Pfeffer, Sternanis")
    res = catalog.resolve_for_stock("cloves", items)
    assert res["kind"] == "in_blend"  # cloves hide in the five-spice mix
    assert "5 Gewürtz" in res["item_name"]
    # garlic being *in* the Cajun mix must NOT make garlic available
    res = catalog.resolve_for_stock("garlic", items)
    assert res["kind"] == "buy"


def test_cascade_components_and_buy():
    # >=50% of garam masala's components stocked (4 of 6)
    items = _items("Kardamom Saat", "Ceylon Zimt", "Gewürznelken",
                   "Koriandersaat", "Pfeffer")
    res = catalog.resolve_for_stock("garam masala", items)
    assert res["kind"] == "components"
    assert "Selbst mischen" in res["note"]
    assert res.get("buy_name") == "Garam Masala"
    res = catalog.resolve_for_stock("butter", [])
    assert res["kind"] == "buy"
    assert res["buy_name"] == "Butter"


def test_cascade_water_staple():
    assert catalog.resolve_for_stock("water", _items())["kind"] == "staple"


# --------------------------------------------------------- junk rules
def test_junk_equipment_and_noise():
    assert catalog.junk_class("Spätzlepresse oder") == "equipment"
    assert catalog.junk_class("große, beschichtete Pfanne") == "equipment"
    assert catalog.junk_class("Minuten") == "noise"
    assert catalog.junk_class("packet") == "noise"
    assert catalog.junk_class("Produkte") == "noise"
    assert catalog.junk_class("Knoblauch") is None


def test_item_containment_guard_and_families():
    # "... mit Hackfleisch" is an ingredient list, not the food: a soup
    # must never resolve to mince
    assert catalog.resolve_item_concept(
        {"name": "Erasco Käse-Lauch-Suppe mit Hackfleisch 4037300115000"}) is None
    # short aliases need start-of-name: "Aubergine" in a spread name is not
    # fresh aubergine
    assert catalog.resolve_item_concept(
        {"name": "Vegane Bio-Streichcreme - Aubergine"}) is None
    # ...but branded suffixed oils still resolve
    assert catalog.resolve_item_concept(
        {"name": "Natives Olivenöl Bio"}) == "olive_oil"
    # kitchen-shelf family defaults
    assert catalog.FAMILY_DEFAULT_CATEGORY["spice"] == "Spices"
    assert catalog.FAMILY_DEFAULT_CATEGORY["blend"] == "Spices"
    assert catalog.FAMILY_DEFAULT_CATEGORY["flour"] == "Baking"
    assert catalog.FAMILY_DEFAULT_CATEGORY["dairy"] == "Dairy"
    assert catalog.FAMILY_DEFAULT_CATEGORY["aromatic"] == "Produce"
    assert catalog.FAMILY_DEFAULT_CATEGORY["oil"] == "Pantry"


def test_prepared_references():
    assert catalog.is_prepared_reference("cooked rice", "cooked rice")
    assert catalog.is_prepared_reference("150 g cooked rice", "cooked rice")
    assert catalog.is_prepared_reference(
        "soy sauce eggs (see my recipe)", "soy sauce eggs")
    assert catalog.is_prepared_reference(
        "1 portion the marinade", "the marinade")
    assert not catalog.is_prepared_reference("200 g Reis", "Reis")


# ----------------------------------------------------- import pipeline
def test_parse_us_volume_with_grams():
    parsed = __import__("app.extract", fromlist=["x"]).parse_ingredient_line(
        "2 cups (300g) frozen blueberries")
    assert parsed["amount"] == 0.3 and parsed["unit"] == "kg"
    assert parsed["name"] == "frozen blueberries"
    parsed = __import__("app.extract", fromlist=["x"]).parse_ingredient_line(
        "0.75 cup caster sugar (165g)")
    assert parsed["amount"] == 0.165 and parsed["unit"] == "kg"


def test_parse_pack_and_fractions_and_and_prefix():
    ex = __import__("app.extract", fromlist=["x"])
    parsed = ex.parse_ingredient_line("1 x 700g glass jar tomato passata")
    assert parsed["amount"] == 0.7 and parsed["unit"] == "kg"
    assert parsed["name"] == "tomato passata"
    parsed = ex.parse_ingredient_line("1 packet of spaghetti")
    assert parsed["name"] == "spaghetti"
    parsed = ex.parse_ingredient_line("1/2 teaspoon salt")
    assert parsed["name"] == "salt"
    parsed = ex.parse_ingredient_line("And 1/2 Tablespoons active dry yeast")
    assert parsed["name"] == "active dry yeast"
    # plain metric lines must never be rewritten
    parsed = ex.parse_ingredient_line("500 g Nudeln")
    assert parsed["raw"] == "500 g Nudeln"


def test_import_drops_equipment_and_marks_prepared(client):
    text = """Spätzle
Zutaten für 2 Portionen:
400 g Mehl
Schaumlöffel
1 Prise Salz
300 g cooked rice from earlier
Alles verrühren."""
    recipe = client.post("/api/recipes/import",
                         json={"kind": "text", "value": text}).json()
    names = [i["raw"] for i in recipe["ingredients"]]
    assert "Schaumlöffel" not in names  # equipment never enters the list
    cooked = next(i for i in recipe["ingredients"] if "cooked rice" in i["raw"])
    assert cooked["tracked"] == 0  # prepared references are availability rows
    mehl = next(i for i in recipe["ingredients"] if i["raw"] == "400 g Mehl")
    assert mehl["itemId"]  # identity match to the seeded Mehl item


# ------------------------------------------------- standardize job
def test_standardize_preserves_confirmed_and_drops_junk(client):
    text = """Pasta
Zutaten für 2:
200 g Spaghetti
Schaumlöffel
1 Prise Salz
1 TL Garam Masala
Kochen."""
    recipe = client.post("/api/recipes/import",
                         json={"kind": "text", "value": text}).json()
    raws = [i["raw"] for i in recipe["ingredients"]]
    assert "Schaumlöffel" not in raws  # import itself drops equipment now
    spaghetti = next(i for i in recipe["ingredients"]
                     if i["raw"] == "200 g Spaghetti")
    # user confirms a match explicitly - the standardize run must keep it
    response = client.post(
        f"/api/recipes/{recipe['id']}/ingredients/{spaghetti['id']}/match",
        json={"item_name": "Mehl"})
    assert response.status_code == 200
    result = client.post("/api/catalog/standardize").json()
    assert result["itemsTagged"] > 0
    recipe = next(r for r in client.get("/api/recipes").json()
                  if r["id"] == recipe["id"])
    raws = [i["raw"] for i in recipe["ingredients"]]
    assert "Schaumlöffel" not in raws
    kept = next(i for i in recipe["ingredients"] if i["raw"] == "200 g Spaghetti")
    assert kept["itemId"] is not None  # confirmed match preserved
    masala = next(i for i in recipe["ingredients"]
                  if "Garam Masala" in i["raw"])
    assert masala["suggestion"] == "Garam Masala"  # buy name preserved


def test_standardize_is_idempotent(client):
    first = client.post("/api/catalog/standardize").json()
    second = client.post("/api/catalog/standardize").json()
    assert second["matched"] == 0  # nothing new to link on a re-run
    assert not second["dropped"]


# ------------------------------------------------- manual create/edit
def test_manual_create_and_tag_editing(client):
    # full-attribute manual creation: concept auto-resolves from the name,
    # the user's category wins over the family default
    response = client.post("/api/items", json={
        "name": "Kreuzkümmel gemahlen", "category": "Spices", "unit": "g",
        "quantity": 2.5,               # > 1 -> flips to qty tracking
        "packageSize": 100, "buyAmount": 200, "minQuantity": 0.5,
    })
    assert response.status_code == 200, response.text
    item = response.json()
    assert item["conceptId"] == "cumin"
    assert item["category"] == "Spices"      # explicit choice respected
    assert item["trackingMode"] == "qty"
    assert item["quantity"] > 0
    # duplicate name rejected
    response = client.post("/api/items", json={"name": "Kreuzkümmel gemahlen"})
    assert response.status_code == 409
    # unknown concept rejected
    response = client.post("/api/items", json={"name": "Sonstwas", "concept_id": "nonsense"})
    assert response.status_code == 400
    # concept editing on the update endpoint: set, then clear
    response = client.post(f"/api/items/{item['id']}/update",
                           json={"concept_id": "turmeric"})
    assert response.status_code == 200 and response.json()["conceptId"] == "turmeric"
    assert response.json()["conceptLabel"] == "Kurkuma"
    response = client.post(f"/api/items/{item['id']}/update",
                           json={"concept_id": ""})
    assert response.status_code == 200 and response.json()["conceptId"] is None


def test_catalog_resolve_helper(client):
    r = client.get("/api/catalog/resolve", params={"name": "cinnamon sticks"})
    assert r.status_code == 200
    assert r.json()["conceptId"] == "cinnamon_stick"
    assert r.json()["label"] == "Zimtstangen"
    r = client.get("/api/catalog/resolve", params={"name": "gibberisch zeug"})
    assert r.status_code == 200 and r.json()["conceptId"] is None


def test_manual_create_without_category_uses_family(client):
    response = client.post("/api/items", json={"name": "Gochujang"})
    assert response.status_code == 200
    assert response.json()["category"] == "Pantry"   # condiment family default
    client.delete(f"/api/items/{response.json()['id']}")


# ------------------------------------------------- BOUGHT concept dedupe
def test_bought_scan_reuses_concept_item(client, monkeypatch):
    from app import products
    existing = repo.find_item_by_name("Kichererbsen") or repo.create_item(
        name="Kichererbsen", unit="kg", package_size=0.4)
    monkeypatch.setattr(products, "product_info", lambda barcode: dict(
        existing, name="CECI SOTTOVUOTO", quantity="530 g",
        categories=[], brand=None, image_url=None))
    barcode = "9876543210987"
    response = client.post("/api/scan/purchase", json={"barcode": barcode})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == existing["id"]  # attached to the generic chickpeas
    assert barcode in (body.get("barcodes") or [])
