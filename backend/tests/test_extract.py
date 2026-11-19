import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.extract import (  # noqa: E402
    extract_schema_org_recipe,
    heuristic_recipe,
    html_to_text,
    normalize_tags,
    og_image_url,
    parse_duration_minutes,
    parse_ingredient_line,
    recipe_meta_from_schema,
)


def test_parse_ingredient_line_grams():
    parsed = parse_ingredient_line("500 g Mehl")
    assert parsed["amount"] == 0.5
    assert parsed["unit"] == "kg"
    assert parsed["name"] == "Mehl"


def test_parse_ingredient_line_comma_decimal():
    parsed = parse_ingredient_line("1,5 kg Kartoffeln")
    assert parsed["amount"] == 1.5
    assert parsed["unit"] == "kg"


def test_parse_ingredient_line_unconvertible_unit():
    parsed = parse_ingredient_line("2 EL Olivenöl")
    assert parsed["amount"] is None
    assert parsed["name"] == "Olivenöl"


def test_parse_ingredient_line_pieces():
    parsed = parse_ingredient_line("3 Eier")
    assert parsed["amount"] == 3
    assert parsed["unit"] == "pcs"


def test_parse_ingredient_line_unicode_fraction():
    parsed = parse_ingredient_line("1½ tsp ground cumin")
    assert parsed["amount"] is None
    assert parsed["name"] == "ground cumin"

    parsed = parse_ingredient_line("½ tsp ground turmeric")
    assert parsed["amount"] is None
    assert parsed["name"] == "ground turmeric"


def test_parse_ingredient_line_range():
    parsed = parse_ingredient_line("1 - 2 tbsp caster sugar")
    assert parsed["amount"] is None
    assert parsed["name"] == "caster sugar"


def test_parse_ingredient_line_leading_parenthetical():
    parsed = parse_ingredient_line("250ml (1 cup) water")
    assert parsed["amount"] == 0.25
    assert parsed["unit"] == "l"
    assert parsed["name"] == "water"


def test_schema_org_howto_sections():
    html = '''<html><head><script type="application/ld+json">
    {"@type": "Recipe", "name": "X", "recipeYield": "2",
     "recipeIngredient": ["100 g Reis"],
     "recipeInstructions": [
       {"@type": "HowToSection", "name": "Cook",
        "itemListElement": [{"@type": "HowToStep", "text": "Boil water."},
                            {"@type": "HowToStep", "text": "Add rice."}]}
     ]}
    </script></head></html>'''
    recipe = extract_schema_org_recipe(html, "https://example.com/x")
    assert recipe is not None
    assert recipe["steps"] == ["Boil water.", "Add rice."]


def test_heuristic_recipe_splits_ingredients_and_steps():
    text = """Pfannkuchen
500 g Mehl
250 ml Milch
2 Eier
Den Teig verrühren.
Bei mittlerer Hitze backen."""
    recipe = heuristic_recipe(text)
    assert recipe["title"] == "Pfannkuchen"
    assert len(recipe["ingredients"]) == 3
    assert len(recipe["steps"]) == 2
    assert recipe["ingredients"][0]["name"] == "Mehl"


SCHEMA_HTML = """<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Recipe", "name": "Bolognese",
 "recipeYield": "4 Portionen",
 "recipeIngredient": ["500 g Hackfleisch", "1 Dose Tomaten"],
 "recipeInstructions": [{"@type": "HowToStep", "text": "Fry the meat."}, {"@type": "HowToStep", "text": "Add tomatoes."}]}
</script>
</head><body></body></html>"""


def test_schema_org_extraction():
    recipe = extract_schema_org_recipe(SCHEMA_HTML, "https://example.com/bolognese")
    assert recipe is not None
    assert recipe["title"] == "Bolognese"
    assert recipe["base_portions"] == 4
    assert recipe["ingredients"][0]["amount"] == 0.5
    assert recipe["ingredients"][0]["unit"] == "kg"
    assert len(recipe["steps"]) == 2


def test_html_to_text_strips_scripts():
    text = html_to_text("<html><script>var x=1;</script><body><p>Hello</p><p>500 g Mehl</p></body></html>")
    assert "var x" not in text
    assert "500 g Mehl" in text


def test_parse_duration_minutes_iso():
    assert parse_duration_minutes("PT30M") == 30
    assert parse_duration_minutes("PT1H30M") == 90
    assert parse_duration_minutes("PT45S") == 0.75
    assert parse_duration_minutes("P1DT30M") == 1470


def test_parse_duration_minutes_text_and_numbers():
    assert parse_duration_minutes("90 minutes") == 90
    assert parse_duration_minutes("1 hour") == 60
    assert parse_duration_minutes(30) == 30
    assert parse_duration_minutes("") is None
    assert parse_duration_minutes(None) is None


def test_normalize_tags_maps_aliases():
    assert normalize_tags("Quick & easy, Chicken, Pasta, One Pan") == [
        "Quick", "Chicken", "Pasta", "One Pan",
    ]
    assert normalize_tags(["seafood", "BBQ", "veggie"]) == [
        "Fish and Seafood", "BBQ", "Vegetarian",
    ]


def test_normalize_tags_dedupes_and_keeps_all():
    assert normalize_tags("Chicken, chicken, CHICKEN, Beef") == ["Chicken", "Beef"]
    assert len(normalize_tags(",a,b,c,d,e,f,g,h,i,j")) == 10
    # >3-word SEO phrases and overlong strings are dropped
    assert normalize_tags("creamy chicken orzo recipe, Quick, " + "x" * 50) == ["Quick"]


def test_recipe_meta_from_schema_andy_cooks_shape():
    node = {
        "@type": "Recipe",
        "prepTime": "PT10M",
        "cookTime": "PT20M",
        "readOnly": True,
        "recipeCuisine": "Italian",
        "recipeCategory": "Dinner",
        "keywords": "Marry Me Chicken Risoni, Dinner, Italian, Chicken, Pasta, One Pan, Quick & easy, "
                    "chicken risoni with parmesan",
        "image": ["https://cdn.example.com/risoni.jpg"],
    }
    meta = recipe_meta_from_schema(node)
    assert meta["prep_minutes"] == 10
    assert meta["cook_minutes"] == 20
    assert meta["total_minutes"] == 30
    assert meta["cuisine"] == "Italian"
    assert meta["category"] == "Dinner"
    assert meta["tags"] == ["Dinner", "Italian", "Chicken", "Pasta", "One Pan", "Quick"]
    assert meta["image_url"] == "https://cdn.example.com/risoni.jpg"


def test_recipe_meta_total_falls_back_to_prep_plus_cook_and_image_dict():
    node = {"preparationTime": None, "prepTime": "PT15M", "cookTime": 45,
            "image": {"url": "https://cdn.example.com/x.jpg"}}
    meta = recipe_meta_from_schema(node)
    assert meta["prep_minutes"] == 15
    assert meta["cook_minutes"] == 45
    assert meta["total_minutes"] == 60
    assert meta["image_url"] == "https://cdn.example.com/x.jpg"
    assert "cuisine" not in meta


def test_og_image_url():
    html = '<meta property="og:image" content="https://img.example.com/a.jpg">'
    assert og_image_url(html) == "https://img.example.com/a.jpg"
    assert og_image_url("<html></html>") is None


def test_schema_org_recipe_includes_meta():
    html = '''<html><head><script type="application/ld+json">
    {"@type": "Recipe", "name": "Risoni", "recipeYield": "4",
     "prepTime": "PT10M", "cookTime": "PT20M",
     "recipeCuisine": "Italian", "recipeCategory": "Dinner",
     "keywords": ["Chicken", "Pasta", "One Pan", "Quick & easy"],
     "image": "https://cdn.example.com/risoni.jpg",
     "recipeIngredient": ["300 g risoni"],
     "recipeInstructions": "Cook the risoni."}
    </script></head></html>'''
    recipe = extract_schema_org_recipe(html, "https://example.com/risoni")
    assert recipe["total_minutes"] == 30
    assert recipe["cuisine"] == "Italian"
    assert recipe["tags"] == ["Chicken", "Pasta", "One Pan", "Quick"]
    assert recipe["image_url"] == "https://cdn.example.com/risoni.jpg"


def test_normalize_tags_drops_seo_phrases():
    # trailing "recipe" suffix and title-restating phrases are filtered
    tags = normalize_tags(
        "Dinner, Japanese, Chicken, Chicken teriyaki recipe, Japanese chicken teriyaki, "
        "Homemade teriyaki sauce, Quick & easy",
        exclude="Chicken teriyaki",
    )
    assert tags == ["Dinner", "Japanese", "Chicken", "Quick"]


def test_split_alternative_names_and_or():
    from app.extract import split_alternative_names
    # the Andy Cooks-style bolded side note, including the mistyped "and or"
    assert split_alternative_names("**Basmati rice and or naan to serve**") == ["Basmati rice", "Naan"]
    assert split_alternative_names("Reis und/oder Nudeln") == ["Reis", "Nudeln"]
    assert split_alternative_names("soy sauce or hoisin") == ["Soy sauce", "Hoisin"]
    # plain "and" means both items are needed: no alternative group
    assert split_alternative_names("salt and pepper") == []
    assert split_alternative_names("Orange marmalade") == []


def test_expand_alternatives_groups_members():
    from app.extract import expand_alternatives
    ingredients = [
        {"raw": "500 g Mehl", "amount": 0.5, "unit": "kg", "name": "Mehl"},
        {"raw": "**Basmati rice and/or naan to serve**", "amount": None, "unit": None,
         "name": "**Basmati rice and/or naan to serve**"},
    ]
    expanded = expand_alternatives(ingredients)
    assert len(expanded) == 3
    assert "alt_group" not in expanded[0]
    rice, naan = expanded[1], expanded[2]
    assert rice["alt_group"] == naan["alt_group"]
    assert rice["raw"] == "Basmati rice"
    assert naan["raw"] == "Naan"
    assert rice["amount"] is None and naan["amount"] is None


def test_expand_alternatives_keeps_amount():
    from app.extract import expand_alternatives
    expanded = expand_alternatives([
        {"raw": "2 EL soy sauce or hoisin", "amount": None, "unit": None, "name": "soy sauce or hoisin"},
    ])
    assert len(expanded) == 2
    assert all(e["alt_group"] == expanded[0]["alt_group"] for e in expanded)


def test_heuristic_recipe_splits_alternative_line_without_amount():
    text = "Curry\n500 g Mehl\n**Basmati rice and/or naan to serve**\nAlles verrühren."
    recipe = heuristic_recipe(text)
    rice = next(i for i in recipe["ingredients"] if i["raw"] == "Basmati rice")
    naan = next(i for i in recipe["ingredients"] if i["raw"] == "Naan")
    assert rice["alt_group"] == naan["alt_group"]
    # the and/or side line is an ingredient, not lost to the steps
    assert not any("naan" in s.lower() for s in recipe["steps"])


def test_link_ingredients_in_steps_every_mention(monkeypatch):
    from app import llm
    from app.extract import link_ingredients_in_steps
    monkeypatch.setattr(llm, "step_aliases", lambda *a, **k: {})
    ingredients = [
        {"raw": "500 g Mehl", "amount": 0.5, "unit": "kg"},
        {"raw": "2 Zwiebeln", "amount": 2, "unit": "pcs"},
        {"raw": "1 Prise Salz", "amount": None},  # unquantified: never tagged
    ]
    steps = [
        "Die Zwiebeln anschwitzen und die Zwiebeln glasig dünsten.",
        "Mehl und Salz verrühren.",
    ]
    links = link_ingredients_in_steps(steps, ingredients)
    step0 = [l for l in links if l["step"] == 0]
    step1 = [l for l in links if l["step"] == 1]
    # every mention gets its own span
    assert [l["ing"] for l in step0] == [1, 1]
    assert steps[0][step0[0]["start"]:step0[0]["end"]].lower() == "zwiebeln"
    assert steps[0][step0[1]["start"]:step0[1]["end"]].lower() == "zwiebeln"
    assert step0[0]["start"] != step0[1]["start"]
    # Mehl quantified -> tagged; Salz (unquantified) -> not
    assert [l["ing"] for l in step1] == [0]
    assert steps[1][step1[0]["start"]:step1[0]["end"]].lower() == "mehl"


def test_link_ingredients_in_steps_plural_and_longest_first(monkeypatch):
    from app import llm
    from app.extract import link_ingredients_in_steps
    monkeypatch.setattr(llm, "step_aliases", lambda *a, **k: {})
    ingredients = [
        {"raw": "1 onion", "amount": 1, "unit": "pcs"},
        {"raw": "1 tsp ground cumin", "amount": 1, "unit": "pcs"},
        {"raw": "1 tsp cumin seeds", "amount": 1, "unit": "pcs"},
    ]
    steps = ["Chop the onions, toast the ground cumin and the cumin seeds."]
    links = link_ingredients_in_steps(steps, ingredients)
    spans = {(l["ing"], steps[0][l["start"]:l["end"]].lower()) for l in links}
    assert (0, "onions") in spans  # naive plural matched
    assert (1, "ground cumin") in spans  # longest first: not stolen by "cumin"
    assert (2, "cumin seeds") in spans
    assert all(l["ing"] == 0 for l in links if "onion" in steps[0][l["start"]:l["end"]])


def test_link_ingredients_in_steps_uses_llm_aliases(monkeypatch):
    from app import llm
    from app.extract import link_ingredients_in_steps
    # LLM proposes "garlic" for Knoblauch; hallucinated phrases are absent
    # from the steps and therefore simply never match
    monkeypatch.setattr(llm, "step_aliases",
                        lambda names, steps, choice=None, cloud=None: {"Knoblauch": ["garlic"]})
    ingredients = [{"raw": "2 Zehen Knoblauch", "amount": 2, "unit": "pcs"}]
    links = link_ingredients_in_steps(["Crush the garlic and the Knoblauch."], ingredients)
    matched = [l for l in links if l["step"] == 0]
    texts = ["Crush the garlic and the Knoblauch."[l["start"]:l["end"]].lower() for l in matched]
    assert sorted(texts) == ["garlic", "knoblauch"]


def test_llm_step_aliases_guarded(monkeypatch):
    from app import llm
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: {
        "aliases": {
            "Mehl": ["flour", "the dough", 5, "a very long phrase that goes on and on way too far"],
            "NotAnIngredient": ["x"],
            "Zwiebeln": ["Zwiebeln"],
        }
    })
    aliases = llm.step_aliases(["Mehl", "Zwiebeln"], ["Mix the flour."])
    # digit and 8-word junk dropped, self-alias dropped, unknown key dropped;
    # "the dough" is a plausible 2-word noun phrase and stays
    assert aliases == {"Mehl": ["flour", "the dough"]}


def test_link_ingredients_wrong_alias_never_steals_a_name(monkeypatch):
    from app import llm
    from app.extract import link_ingredients_in_steps
    # the LLM hallucinated: it proposed "Zwiebeln" and "Butter" as aliases of
    # Basmatireis. Real names own their mentions; the junk aliases are dropped.
    monkeypatch.setattr(llm, "step_aliases", lambda *a, **k: {"Basmatireis": ["Zwiebeln", "Butter"]})
    ingredients = [
        {"raw": "250 g Basmatireis", "amount": 0.25, "unit": "kg"},
        {"raw": "2 Zwiebeln", "amount": 2, "unit": "pcs"},
    ]
    steps = ["Die Zwiebeln anrösten. Den Basmatireis mit Zwiebeln servieren."]
    links = link_ingredients_in_steps(steps, ingredients)
    spans = [(l["ing"], steps[0][l["start"]:l["end"]]) for l in links]
    assert (0, "Basmatireis") in spans
    assert (1, "Zwiebeln") in spans
    assert all(ing == 1 for ing, text in spans if "Zwiebel" in text), spans
    assert all(ing == 0 for ing, text in spans if text == "Basmatireis"), spans


def test_llm_recipe_repairs_unit_only_ingredient_names(monkeypatch):
    from app import extract
    # the local 3b model sometimes drops the food from the name and dumps
    # the amount on the unit-only leftover ("250 g", amount 250)
    monkeypatch.setattr(extract.llm, "generate_json", lambda *a, **k: {
        "title": "Test", "basePortions": 4,
        "ingredients": [
            {"raw": "250 g Basmatireis", "amount": 250, "unit": "g", "name": "250 g"},
            {"raw": "2 Zwiebeln", "amount": 2, "unit": "pcs", "name": "Zwiebeln"},
        ],
        "steps": ["Reis kochen."],
    })
    recipe = extract.llm_recipe("egal", "pasted")
    by_name = {i["name"]: i for i in recipe["ingredients"]}
    assert by_name["Basmatireis"]["amount"] == 0.25
    assert by_name["Basmatireis"]["unit"] == "kg"
    assert by_name["Zwiebeln"]["amount"] == 2
