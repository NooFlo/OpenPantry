import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.extract import (  # noqa: E402
    extract_schema_org_recipe,
    heuristic_recipe,
    html_to_text,
    parse_ingredient_line,
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
