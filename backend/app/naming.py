"""Deterministic generic naming — the brand-free identity everything matches on.

Three views of the same food reduce to one comparable string:

    inventory item  "Alnatura Bio Basmatireis 500 g"  ->  "basmatireis"
    recipe line     "300g Basmatireis"                ->  "basmatireis"
    receipt line    "ALNATURA REIS BASMATI 500G"      ->  "reis basmati"

Conservative by design: digit junk, prices, size stamps and curated
brands/qualifiers go; every unknown word survives. Form words ("grob",
"fein", "ganz", "geschält") are *not* junk — they distinguish real
products ("Haferflocken fein" vs "Haferflocken grob") and stay.
"""

import re

from .catalog import CONCEPTS

# store brands and producer brands that ride along on product names;
# matched word-tight, extended as receipts teach us more
BRANDS = {
    "alnatura", "alpro", "appelita", "asdo", "barilla", "bauck",
    "bionade", "bionella", "caotina", "dennree", "erasco", "ferrero",
    "k-classic", "kerrygold", "knorr", "kruger", "krüger", "lieken",
    "maggi", "milbona", "milram", "mövenpick", "movenpick", "nestle",
    "oetker", "ostmann", "panzani", "rapunzel", "ruf", "sanella",
    "sudzucker", "südzucker", "teekanne", "thomy", "tip", "werz",
    "edeka", "gut bio",
}

# marketing / packaging qualifiers — never part of a generic name
QUALIFIERS = {
    "bio", "organic", "premium", "delikatess", "original", "classic",
    "klassisch", "selection",
}

# junk stripped from a line before word filtering: EAN-like runs, prices
# ("1.89€", "€1.89", "1,89 EUR" as one token), size stamps with a unit
JUNK_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\b\d{8,14}\b",                                       # EAN-like runs
    r"\b\d+(?:[.,]\d+)?\s*(?:g|kg|ml|cl|dl|stk|pcs|cm|mm)\b",  # size stamps
    r"[€$]\s*\d+(?:[.,]\d+)?",                             # €1.89
    r"\b\d+(?:[.,]\d+)?\s*(?:eur|usd)\b",                  # 1.89 eur
    r"\b\d+(?:[.,]\d+)?\s*l\b",                            # 0,5 l / 1 l / 1.5l
))

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_WORD_SPLIT = re.compile(r"[^\wäöüß+]+")


def clean(text: str) -> str:
    """Product/receipt line -> brand-free generic name ('' when nothing
    edible survives). Words we don't know are never removed."""
    for pattern in JUNK_RES:
        text = pattern.sub(" ", text or "")
    kept = []
    for word in _WORD_SPLIT.split((text or "").lower()):
        if not word or word in BRANDS or word in QUALIFIERS:
            continue
        if _NUMBER.fullmatch(word):  # bare numbers ("5", "1,5")
            continue
        kept.append(word)
    if not kept:
        return ""
    out = " ".join(kept)
    return out[0].upper() + out[1:]


def auto(name: str, concept_id: str | None = None) -> str:
    """Generic name for a row with `name` and optional resolved concept:
    the curated concept label first, the cleaned name otherwise."""
    label = concept_label(concept_id)
    return label or clean(name) or (name or "").strip()


def concept_label(concept_id: str | None) -> str | None:
    """Curated German display label for a concept id, if it exists."""
    if concept_id and concept_id in CONCEPTS:
        return CONCEPTS[concept_id].get("de")
    return None


def ingredient_generic_name(raw: str, concept_id: str | None = None) -> str:
    """Generic name for a recipe ingredient row: the curated concept label
    when the row resolved to a concept, the cleaned raw text otherwise."""
    if concept_id and concept_id in CONCEPTS:
        return CONCEPTS[concept_id].get("de") or clean(raw)
    return clean(raw) or (raw or "").strip()
