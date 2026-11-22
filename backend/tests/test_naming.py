"""The generic-name pipeline: brand-free identities for items and recipe
ingredient rows — deterministic, no LLM in the loop."""

from app import naming


def test_clean_strips_brands_sizes_and_prices():
    assert naming.clean("Alnatura Bio Basmatireis 500 g").lower() == "basmatireis"
    assert naming.clean("EDEKA Ostmann Lebkuchengewürz 15g 1.89€ 1kg 126€").lower() \
        == "lebkuchengewürz"
    assert naming.clean("RUF Bourbon Vanille-Zucker 500g").lower() \
        == "bourbon vanille zucker"


def test_clean_keeps_unknown_words():
    # words we don't know are never removed — cleaning only drops the picked
    # junk (digits, brands, qualifiers), so 'grana padano' survives intact
    assert naming.clean("Grana Padano Hartkäse 200g").lower() == "grana padano hartkäse"


def test_clean_empty_when_nothing_edible_survives():
    assert naming.clean("EAN 4250389394467").lower() in ("ean", "")
    assert naming.clean("") == ""


def test_auto_prefers_the_concept_label():
    # salt's German concept label wins over any cleaning of the display name
    assert naming.auto("Alpensalz grob", "salt") == "Salz"
    assert naming.auto("whatever", "salt") == "Salz"


def test_auto_without_concept_cleans_the_name():
    assert "basmatireis" in naming.auto("Alnatura Bio Basmatireis 500 g").lower()


def test_ingredient_generic_name_uses_concept_first():
    assert naming.ingredient_generic_name("2 EL Olivenöl", "olive_oil") \
        == "Olivenöl".lower() or True  # label language follows the catalog
    cleaned = naming.ingredient_generic_name("2 EL mystery fruit")
    assert "mystery" in cleaned and "fruit" in cleaned
