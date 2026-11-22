import json
import re
import shutil
import subprocess
import uuid

import httpx

from . import llm, telemetry

UNIT_ALIASES = {
    "g": "g", "gr": "g", "gramm": "g",
    "kg": "kg", "kilogramm": "kg",
    "ml": "ml", "milliliter": "ml",
    "l": "l", "liter": "l",
    "pcs": "pcs", "piece": "pcs", "pieces": "pcs", "stueck": "pcs", "stück": "pcs", "stk": "pcs",
}

INGREDIENT_RE = re.compile(
    r"^\s*(\d+(?:[.,]\d+)?)(?:\s*(?:-|–|to)\s*(\d+(?:[.,]\d+)?))?\s*"
    r"(g|gr|gramm|kg|kilogramm|ml|milliliter|l|liter|pcs?|pieces?|stk|stück|stueck|tsp|teaspoon|teaspoons|tbsp|tbs|tablespoons?|tablespoon|EL|TL|Prise|Zehe[n]?|Handvoll|pinch|handful|splash|clove[s]?|pod[s]?|sprig[s]?|stick[s]?|can[s]?|cup[s]?)?\s+"
    r"(.+?)\s*$",
    re.IGNORECASE,
)

# Andy Cooks filter chips: the fixed set the recipe list offers above the
# tag chips. Any other tag stays on the recipe but gets no filter chip.
CATEGORY_FILTERS = [
    "Quick", "Chicken", "Beef", "Pasta", "Fish and Seafood", "Vegetarian", "Comfort Food",
    "Slow Cooked", "BBQ", "Burgers and Sandwiches", "Curry", "Noodles", "Pork", "Lamb",
    "Dessert", "Breakfast", "Salad", "Soup",
]
TAG_ALIASES = {
    "quick": "quick", "quick & easy": "quick", "quick and easy": "quick", "easy": "quick",
    "weeknight": "quick", "fast": "quick",
    "chicken": "chicken",
    "beef": "beef",
    "pasta": "pasta",
    "fish": "fish and seafood", "seafood": "fish and seafood", "fish and seafood": "fish and seafood",
    "fish & seafood": "fish and seafood", "shellfish": "fish and seafood",
    "vegetarian": "vegetarian", "veggie": "vegetarian", "plant based": "vegetarian",
    "comfort food": "comfort food", "comfort": "comfort food",
    "slow cooked": "slow cooked", "slow cook": "slow cooked", "slow-cooked": "slow cooked",
    "bbq": "bbq", "barbecue": "bbq",
    "burgers and sandwiches": "burgers and sandwiches", "burgers & sandwiches": "burgers and sandwiches",
    "burger": "burgers and sandwiches", "burgers": "burgers and sandwiches",
    "sandwich": "burgers and sandwiches", "sandwiches": "burgers and sandwiches",
    "curry": "curry", "curries": "curry",
    "noodles": "noodles", "noodle": "noodles",
    "pork": "pork",
    "lamb": "lamb",
    "dessert": "dessert", "desserts": "dessert", "sweet": "dessert",
    "breakfast": "breakfast", "brekkie": "breakfast",
    "salad": "salad", "salads": "salad",
    "soup": "soup", "soups": "soup",
}
ISO_DURATION_RE = re.compile(
    r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?",
    re.IGNORECASE,
)
PLAIN_DURATION_RE = re.compile(
    r"(?:(\d+(?:[.,]\d+)?)\s*(?:h(?:our)?s?|std))?\s*(?:(\d+(?:[.,]\d+)?)\s*m(?:in(?:ute)?s?)?)?\s*$",
    re.IGNORECASE,
)
SPOON_UNITS = {"tsp", "teaspoon", "teaspoons", "tbsp", "tbs", "tablespoon", "tablespoons",
               "el", "tl", "prise", "pinch", "handful", "splash", "sprig", "sprigs"}
FRACTIONS = {"½": "0.5", "¼": "0.25", "¾": "0.75", "⅓": "0.33", "⅔": "0.67", "⅛": "0.125"}


def _replace_fractions(line: str) -> str:
    for frac, dec in FRACTIONS.items():
        line = re.sub(r"(\d+)\s*" + frac, lambda m, d=dec: str(float(m.group(1)) + float(d)), line)
        line = line.replace(frac, dec)
    # ASCII fractions: "1/2 lemon" -> "0.5 lemon" (newspaper recipes paste
    # them constantly; the INGREDIENT_RE can't match bare "1/2")
    def _ascii_frac(match):
        a, b = int(match.group(1)), int(match.group(2))
        return f"{a / b:.3f}".rstrip("0").rstrip(".") if b else match.group(0)
    line = re.sub(r"\b(\d+)\s*/\s*(\d+)\b", _ascii_frac, line)
    return line
STEP_HINTS = re.compile(r"\b(minut|min\.|backen|braten|kochen|erhitzen|rühren|ruehren|geben|stir|bake|fry|boil|heat|mix|add|preheat|oven)\b", re.IGNORECASE)

# "post-processed" -> "raw" ingredient names:
# package/measure words and preparation adjectives that get stripped from
# ingredient names so "2 Zehen Knoblauch" -> "Knoblauch". Failing to strip is
# harmless (only affects matching), wrong stripping is not -> explicit sets only.
MEASURE_WORDS = {
    "clove", "cloves", "zehen", "bund", "stange", "stangen", "dose", "dosen", "prise", "prisen",
    "tl", "el", "esslöffel", "teelöffel", "handvoll", "bunch", "stick", "sticks",
    "sprig", "sprigs", "beutel", "packung", "packungen", "flasche", "flaschen", "tassen", "cup", "cups",
    "glass", "gläser", "stange", "scheibe", "scheiben", "ml", "l", "cl", "g", "kg",
}
PREP_WORDS = {
    "gerieben", "geriebener", "geriebene", "geriebenes", "gehackt", "gehackter", "gehackte", "gehacktes",
    "gewürfelt", "gewürfelter", "gewürfelte", "gewürfeltes", "geschält", "geschälte", "geschälter",
    "mehligkochend", "mehligkochende", "mehligkochender", "mehligkochendes",
    "festkochend", "festkochende", "mittlere", "mittlerer", "mittleres", "kleine", "kleiner", "kleines",
    "große", "großer", "großes", "frische", "frischer", "frisches",
    "steamed", "toasted", "grated", "sliced", "chopped", "minced", "diced", "crushed",
    "washed", "peeled", "beaten", "separated", "extra", "virgin",
}
PREP_HINT_RE = re.compile(
    r"grated|sliced|chopped|separated|diced|minced|washed|halved|peeled|beaten|crushed|steamed|toasted"
    r"|thumb|piece|pieces|bunch|stick|clove|to serve|to garnish|to season|nach geschmack|zum würzen"
    r"|gerieben|gehackt|gewürfelt|geschält|geviertelt|in streifen|würfel|fein|mehlig|mittlere|prise|handvoll|bund|zehe|stange|dose",
    re.IGNORECASE,
)


# Sizes measured on the food itself stick to the name when the amount parser
# can't split them ("2.5cm piece fresh ginger"). The number is a quantity.
SIZE_PREFIX_RE = re.compile(
    r"^\s*(\d+(?:[.,]\d+)?)\s*(cm|mm|zoll|inch(?:es)?)\b\s*"
    r"(?:pcs?|pieces?|st\u00fcck(?:e|en)?|scheibe(?:n)?|slices?|sticks?|knob)?\s*[-\u2013]?\s*",
    re.IGNORECASE,
)


def split_size_prefix(name: str) -> tuple[float | None, str | None, str]:
    """Pull a size prefix out of an ingredient name; the size is a quantity
    that belongs to the amount, not the name.

    "2.5cm piece fresh ginger" -> (2.5, "cm", "fresh ginger");
    "3 tbsp olive oil" parses to (None, None, input) — measure amounts
    belong to the amount parser, not here. Unchanged when nothing applies."""
    m = SIZE_PREFIX_RE.match(name or "")
    if not m:
        return None, None, name or ""
    rest = name[m.end():].strip()
    if not rest:
        return None, None, name
    return float(m.group(1).replace(",", ".")), m.group(2).lower(), rest


def base_ingredient_name(name: str) -> str:
    """Reduce a post-processed ingredient description to the raw grocery item.

    Deterministic and conservative: "spring onions, white and green parts
    separated" -> "spring onions", "1 mittlere Karotte (ca. 80 g)" -> "Karotte".
    Returns the input unchanged when nothing applies.
    """
    s = re.sub(r"\([^)]*\)", " ", name).strip()
    if "," in s:
        s = s.split(",", 1)[0].strip()
    tokens = s.split()
    while tokens and re.fullmatch(r"[\d.,/½¼¾⅓⅔⅛]+(?:\s*(?:g|kg|ml|l|cl))?", tokens[0], re.IGNORECASE):
        tokens.pop(0)
    while tokens and tokens[0].lower() in MEASURE_WORDS:
        tokens.pop(0)
    while tokens and tokens[0].lower() in PREP_WORDS:
        tokens.pop(0)
    result = " ".join(tokens).strip(" -–")
    return result if result else name.strip()


def needs_name_canonicalization(name: str) -> bool:
    return bool(PREP_HINT_RE.search(base_ingredient_name(name)))


# "Basmati rice and/or naan to serve" -> ["Basmati rice", "Naan"]:
# one slot in the recipe satisfied by either option. Splitters cover
# English/German "and/or" spellings including the mistyped "and or".
ALT_SPLIT_RE = re.compile(
    r"\s+(?:and\s*/\s*or|and\s+or|und\s*/\s*oder|und\s+oder|or|oder)\s+",
    re.IGNORECASE,
)
# trailing serving/garnish notes suggested by the option, not the pantry item
SERVE_SUFFIX_RE = re.compile(
    r"\s*\b(?:to\s+serve|to\s+garnish|to\s+taste|to\s+accompany|zum\s+servieren|nach\s+geschmack)\b\s*.*$",
    re.IGNORECASE,
)


def strip_markdown(line: str) -> str:
    """Remove emphasis markers web recipes carry into extracted text (**bold**)."""
    return line.replace("*", "").strip()


def _clean_alternative_part(part: str) -> str:
    part = re.sub(r"\([^)]*\)", " ", part)
    part = SERVE_SUFFIX_RE.sub("", part)
    part = re.sub(r"\s+", " ", part).strip(" ,-–—")
    if part:
        part = part[0].upper() + part[1:]
    return part


def split_alternative_names(name: str) -> list[str]:
    """Split a raw ingredient name into its and/or alternatives.

    Returns [] when the name is not a genuine alternative ("salt and
    pepper" stays one line: plain "and" means both items are needed).
    """
    name = strip_markdown(name or "")
    if not ALT_SPLIT_RE.search(name):
        return []
    parts = [_clean_alternative_part(p) for p in ALT_SPLIT_RE.split(name)]
    parts = [p for p in parts if len(re.findall(r"[^\W\d_]", p, re.UNICODE)) >= 2]
    return parts if len(parts) >= 2 else []


def expand_alternatives(ingredients: list[dict]) -> list[dict]:
    """Replace and/or ingredient lines with their options as separate
    entries sharing an alt_group id: exactly one of them is meant to be
    bought/served. Non-splitting lines pass through unchanged."""
    out: list[dict] = []
    for ing in ingredients:
        parts = split_alternative_names(ing.get("name") or ing.get("raw") or "")
        if len(parts) >= 2:
            group = uuid.uuid4().hex[:12]
            for part in parts:
                alt = dict(ing)
                alt["raw"] = part
                alt["name"] = part
                alt["alt_group"] = group
                out.append(alt)
        else:
            out.append(ing)
    return out


def _mention_variants(name: str) -> list[str]:
    """Search variants of an ingredient name: the name itself plus naive
    English plurals ("onion" -> "onions", "oniones" is wrong but harmless —
    a failed match costs nothing)."""
    name = name.strip()
    return [name, name + "s", name + "es"]


def _mention_key(ing: dict) -> str:
    """The text to search for in steps: the parsed ingredient name (units and
    measure words stripped), falling back to deterministic name cleanup."""
    raw = ing.get("name") or ing.get("raw") or ""
    parsed = parse_ingredient_line(raw)
    name = (parsed or {}).get("name") or base_ingredient_name(raw)
    return name


def link_ingredients_in_steps(steps: list[str], ingredients: list[dict],
                              choice: dict | None = None, cloud: dict | None = None) -> list[dict]:
    """Find quantified ingredient mentions in the recipe's step texts.

    Every mention gets its own link (character span within the step) — the
    UI renders a live "(qty)" after each span, scaled by the portions
    stepper. Deterministic word-boundary matching on the cleaned ingredient
    name (longest names first so "ground cumin" wins over "cumin");
    the LLM only contributes extra lookup phrases, which are accepted only
    when found verbatim in the text. `ing` indexes into the ingredient list,
    resolved to real ids by the repo when stored."""
    # quantified ingredients only: unquantified ones (spoon measures etc.)
    # have no per-portion factor to display
    candidates: list[tuple[int, str]] = []  # (ingredient index, base name)
    for index, ing in enumerate(ingredients):
        if ing.get("amount") is None:
            continue
        name = _mention_key(ing)
        if len(re.findall(r"[^\W\d_]", name, re.UNICODE)) >= 2:
            candidates.append((index, name))
    if not candidates or not any((s or "").strip() for s in steps):
        return []
    names = [name for _, name in candidates]
    with telemetry.span("step_aliasing", names=len(names)):
        aliases = llm.step_aliases(names, steps, choice, cloud) or {}
    # aliases never steal a real ingredient's mention: quantified candidates
    # AND unquantified ingredients both own their names in the step text
    names_lower = {name.lower() for _, name in candidates}
    owners = {_mention_key(ing).lower() for ing in ingredients} | names_lower

    links: list[dict] = []
    for step_index, step in enumerate(steps):
        if not step:
            continue
        taken: list[tuple[int, int]] = []
        local: list[dict] = []

        def _claim(index: int, phrase: str, step: str = step, lower: str = step.lower()) -> int:
            """Tag every word-boundary occurrence of phrase not already taken."""
            claimed = 0
            start = 0
            while True:
                found = lower.find(phrase.lower(), start)
                if found < 0:
                    break
                end = found + len(phrase)
                start = end
                before_ok = found == 0 or not re.match(r"[\wÄÖÜäöüß]", step[found - 1], re.UNICODE)
                after_ok = end >= len(step) or not re.match(r"[\wÄÖÜäöüß]", step[end], re.UNICODE)
                overlaps = any(not (end <= s or found >= e) for s, e in taken)
                if before_ok and after_ok and not overlaps:
                    taken.append((found, end))
                    local.append({"step": step_index, "ing": index,
                                  "start": found, "end": end, "name": step[found:end]})
                    claimed += 1
            return claimed

        # phase 1 — the ingredient's own name (naive plurals included).
        # Exact names always claim before aliases, longest first, so
        # "ground cumin" wins over "cumin".
        for index, name in sorted(candidates, key=lambda pair: len(pair[1]), reverse=True):
            for variant in _mention_variants(name):
                _claim(index, variant)
        # phase 2 — LLM-proposed phrases for mentions under a different
        # word ("the marinade", "garlic" for "Knoblauch"). An alias that
        # collides with any ingredient's real name is rejected outright:
        # the name itself owns its mentions.
        for index, name in candidates:
            for alias in aliases.get(name, []):
                alias_lower = alias.lower()
                if any(other == alias_lower or other in alias_lower or alias_lower in other
                       for other in owners):
                    continue
                _claim(index, alias)
        links.extend(sorted(local, key=lambda link: link["start"]))
    return links


HEADER_RE = re.compile(r"^(zutaten|ingredients|servings|preparation|zubereitung)\b|^\W*for \d+ (portions|servings)", re.IGNORECASE)
PORTIONS_RE = re.compile(r"(?:für|for)\s*(\d+)\s*(?:portionen|portions|servings)", re.IGNORECASE)


def normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    key = unit.strip().lower()
    return UNIT_ALIASES.get(key)


def to_base_unit(amount: float, unit: str | None) -> tuple[float, str] | None:
    normalized = normalize_unit(unit)
    if normalized == "g":
        return amount / 1000, "kg"
    if normalized == "ml":
        return amount / 1000, "l"
    if normalized in ("kg", "l", "pcs"):
        return amount, normalized
    return None


def parse_ingredient_line(line: str) -> dict | None:
    line = strip_markdown(line.strip())
    line = _replace_fractions(line)
    # LLM splits like "And 1/2 Tablespoons active dry yeast" leak a leading
    # And/Und into the amount slot
    line = re.sub(r"^(?:and|und)\s+(?=\d)", "", line, flags=re.IGNORECASE)
    # US volume lines that carry their metric equivalent in parens:
    # "2 cups (300g) frozen blueberries" or "0.75 cup caster sugar (165g)"
    vol = re.match(
        r"^(\d+(?:[.,]\d+)?)\s*(?:cups?|tbsp|tbsps?|tablespoons?|tsp|"
        r"teaspoons?|fl\.?\s*oz)\s*\(([^)]*?(\d+(?:[.,]\d+)?)\s*"
        r"(g|gr|gramm|kg|ml|l|liter|milliliter)\b[^)]*)\)\s+(.+?)\s*$",
        line, re.IGNORECASE)
    if vol:
        line = f"{vol.group(3)}{vol.group(4).lower().replace('gramm','g').replace('liter','l').replace('milliliter','ml').replace('gr','g')} {vol.group(5)}"
    else:
        vol2 = re.match(
            r"^(\d+(?:[.,]\d+)?)\s*(?:cups?|tbsp|tbsps?|tablespoons?|tsp|"
            r"teaspoons?)\s+(.+?)\s*\((\d+(?:[.,]\d+)?)\s*"
            r"(g|gr|gramm|kg|ml|l)\)\s*$", line, re.IGNORECASE)
        if vol2:
            line = f"{vol2.group(3)}{vol2.group(4).lower().replace('gramm','g').replace('gr','g')} {vol2.group(2)}"
    # "1 x 700g glass jar tomato passata": multiplier + metric pack before
    # the name — take the grams directly. The "N x" OR a container word must
    # be present, otherwise every "500 g Nudeln" would be rewritten.
    pack = re.match(
        r"^(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)\s*"
        r"(g|gr|gramm|kg|ml|l)\b\s*(.*)$", line, re.IGNORECASE)
    container = re.match(
        r"^(\d+(?:[.,]\d+)?)\s*(g|gr|gramm|kg|ml|l)\s+"
        r"(?:glass\s+jar|glass|jar|bottle|tin|pkt)\b\s+(.*)$",
        line, re.IGNORECASE)
    if pack and pack.group(4):
        line = f"{pack.group(2)}{pack.group(3).lower().replace('gramm','g').replace('gr','g')} {pack.group(4)}"
    elif container and container.group(3):
        line = f"{container.group(1)}{container.group(2).lower().replace('gramm','g').replace('gr','g')} {container.group(3)}"
    match = INGREDIENT_RE.match(line)
    if not match:
        return None
    raw_amount, _range_end, raw_unit, name = match.groups()
    amount = float(raw_amount.replace(",", "."))
    name = re.sub(r"^\s*\([^)]*\)\s*", "", name).strip()
    # containers are packaging, not the food: "packet of spaghetti",
    # "glass jar passata", "pkt Shin Ramen Black"
    for _ in range(3):
        stripped = re.sub(
            r"^(?:pkt|packet|packets|tin|tins|bottle|bottles|glass jar|jar|glass|"
            r"bunch|punnet|head|block|sheet|sheets|strip|strips)\s+(?:of\s+)?",
            "", name, flags=re.IGNORECASE).strip()
        if stripped == name:
            break
        name = stripped
    # serving and taste tails: they belong to prose, not the pantry name
    name = re.sub(
        r",?\s*(?:to serve|to taste|to season|to garnish|for garnish|"
        r"zum servieren|nach geschmack|als beilage|zum bestreuen|"
        r"zum garnieren|see my recipe|see recipe|see below)\b.*$"
        r"|\s+plus\s+.*$", "", name, flags=re.IGNORECASE).strip()
    converted = to_base_unit(amount, raw_unit)
    if converted:
        amount, unit = converted
        return {"raw": line, "amount": round(amount, 4), "unit": unit, "name": name}
    if raw_unit is None:
        return {"raw": line, "amount": amount, "unit": "pcs", "name": name}
    # household measure words (spoons, cloves, handfuls, cups, cm pieces...):
    # the count IS the amount, the unit stays the household word. Displays
    # scale it with the portions setting; stock math never compares these
    # numerically against a kg/l/pcs item (repo.household_row /
    # cooking.ts householdUnit guard that comparison).
    if raw_unit.lower() in SPOON_UNITS:
        name = re.sub(r"^\s*(?:tsp|teaspoons?|tbs|tbsps?|tablespoons?|el|tl|prise|pinch|handful|splash|sprigs?)\s+", "", name, flags=re.IGNORECASE).strip()
    return {"raw": line, "amount": amount, "unit": raw_unit, "name": name}


def parse_duration_minutes(value) -> float | None:
    """Parse ISO 8601 durations (PT1H30M), plain '90 minutes' text or a bare number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, list):
        value = value[0] if value and value[0] is not None else None
        return parse_duration_minutes(value)
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    minutes = None
    if re.match(r"^p", text):
        match = ISO_DURATION_RE.search(text)
        if match:
            days, hours, mins, secs = match.groups()
            minutes = float(days or 0) * 1440 + float(hours or 0) * 60 + float(mins or 0) + float(secs or 0) / 60
    else:
        bare = re.match(r"^\d+(?:[.,]\d+)?$", text)
        if bare:
            minutes = float(text.replace(",", "."))
        else:
            match = PLAIN_DURATION_RE.search(text)
            if match:
                hours, mins = match.groups()
                if hours or mins:
                    minutes = float((hours or "0").replace(",", ".")) * 60 + float((mins or "0").replace(",", "."))
    return minutes if minutes and minutes > 0 else None


CATEGORY_DISPLAY = {chip.lower(): chip for chip in CATEGORY_FILTERS}


def normalize_tags(raw, exclude: str | None = None) -> list[str]:
    """Carry over all source tags onto the canonical taxonomy where one exists.

    Drops the recipe title and long-tail SEO phrases; source keyword lists on
    e.g. andy-cooks.com lead with the dish name and multi-word search phrases.
    Everything else is kept so a source's own tags survive ingestion.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = [str(item) for item in raw]
    else:
        items = str(raw).replace(";", ",").split(",")
    exclude_lower = (exclude or "").strip().lower()
    tags: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = re.sub(r"\s+", " ", item.strip())
        if not tag or len(tag) > 40 or len(tag.split()) > 3:
            continue
        if exclude_lower and tag.lower() == exclude_lower:
            continue
        # SEO synonym phrases, not categories: "...recipe" suffixes and
        # tags that just restate the dish title
        if re.search(r"\brecipe\b|\bhow to\b", tag.lower()):
            continue
        if exclude_lower and exclude_lower in tag.lower():
            continue
        canonical = TAG_ALIASES.get(tag.lower())
        canonical_tag = CATEGORY_DISPLAY.get(canonical, canonical) if canonical else None
        # anything non-canonical with 3+ words is an SEO phrase, not a category
        if canonical_tag is None and len(tag.split()) > 2:
            continue
        tag = canonical_tag if canonical_tag else tag[0].upper() + tag[1:]
        if tag.lower() in seen:
            continue
        seen.add(tag.lower())
        tags.append(tag)
    return tags


def _first_text(value) -> str | None:
    """Schema fields may be str or list; take the first text entry."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _image_url(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("url")
    if isinstance(value, str) and value.startswith("http"):
        return value
    return None


def recipe_meta_from_schema(node: dict) -> dict:
    """Prep/cook/total minutes, cuisine, category, tags, image from a schema.org node."""
    prep = parse_duration_minutes(node.get("prepTime"))
    cook = parse_duration_minutes(node.get("cookTime"))
    total = parse_duration_minutes(node.get("totalTime"))
    if total is None and (prep is not None or cook is not None):
        total = (prep or 0) + (cook or 0) or None
    meta = {
        "prep_minutes": prep,
        "cook_minutes": cook,
        "total_minutes": total,
        "cuisine": _first_text(node.get("recipeCuisine")),
        "category": _first_text(node.get("recipeCategory")),
        "tags": normalize_tags(node.get("keywords"), exclude=node.get("name")),
        "image_url": _image_url(node.get("image")),
    }
    return {k: v for k, v in meta.items() if v is not None and v != []}


def heuristic_recipe(text: str, source: str = "pasted", image_url: str | None = None) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ingredients, steps = [], []
    base_portions = 4
    for line in lines:
        if HEADER_RE.search(line):
            continue
        portions_match = PORTIONS_RE.search(line)
        if portions_match:
            base_portions = float(portions_match.group(1))
            continue
        parsed = parse_ingredient_line(line)
        if parsed and not STEP_HINTS.search(line):
            ingredients.append(parsed)
        elif ALT_SPLIT_RE.search(line) and not STEP_HINTS.search(line):
            # "Basmati rice and/or naan to serve": no measurable amount, but
            # a valid (alternative) ingredient — kept rather than lost to steps
            clean = strip_markdown(line)
            ingredients.append({"raw": clean, "amount": None, "unit": None, "name": clean})
        elif len(line) > 15:
            steps.append(line)
    title = "Imported recipe"
    if lines and not parse_ingredient_line(lines[0]):
        title = lines[0]
    recipe = {
        "title": title,
        "source": source,
        "base_portions": base_portions,
        "ingredients": expand_alternatives(ingredients),
        "steps": steps,
    }
    if image_url:
        recipe["image_url"] = image_url
    return recipe


def extract_schema_org_recipe(html: str, url: str) -> dict | None:
    for match in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE
    ):
        try:
            data = json.loads(match.group(1).strip())
        except ValueError:
            continue
        for node in _iter_jsonld(data):
            if isinstance(node, dict) and node.get("@type") in ("Recipe", ["Recipe"]):
                return _schema_to_recipe(node, url)
    return None


def _iter_jsonld(node):
    if isinstance(node, list):
        for item in node:
            yield from _iter_jsonld(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_jsonld(value)


def _schema_to_recipe(node: dict, url: str) -> dict:
    yield_text = node.get("recipeYield") or node.get("yield")
    base_portions = 4
    if yield_text:
        numbers = re.findall(r"\d+", str(yield_text))
        if numbers:
            base_portions = float(numbers[0])
    ingredients = []
    for raw in node.get("recipeIngredient") or []:
        clean = strip_markdown(str(raw))
        parsed = parse_ingredient_line(clean)
        if parsed:
            ingredients.append(parsed)
        else:
            ingredients.append({"raw": clean, "amount": None, "unit": None, "name": clean})
    steps = []
    raw_steps = node.get("recipeInstructions") or []
    if isinstance(raw_steps, str):
        raw_steps = [raw_steps]
    for step in raw_steps:
        if isinstance(step, dict):
            children = step.get("itemListElement")
            if children:
                for child in children:
                    if isinstance(child, dict):
                        text = child.get("text") or child.get("name") or ""
                        if text:
                            steps.append(str(text))
                    elif child:
                        steps.append(str(child))
                continue
            step = step.get("text") or step.get("name") or ""
        if step:
            steps.append(str(step))
    recipe = {
        "title": str(node.get("name") or "Imported recipe"),
        "source": url,
        "base_portions": base_portions,
        "ingredients": expand_alternatives(ingredients),
        "steps": steps,
    }
    recipe.update(recipe_meta_from_schema(node))
    return recipe


def html_to_text(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def llm_recipe(text: str, source: str, choice: dict | None = None, cloud: dict | None = None,
               image_url: str | None = None) -> dict | None:
    telemetry.set_meta(prompt_chars=len(text), truncated=len(text) > 6000)
    prompt = (
        "Extract the recipe from the following text. Respond with JSON only, in this exact shape:\n"
        '{"title": str, "basePortions": number, '
        '"prepMinutes": number|null, "cookMinutes": number|null, '
        '"cuisine": str|null, "category": str|null, "tags": [str], '
        '"ingredients": [{"raw": str, "amount": number|null, "unit": "g"|"kg"|"ml"|"l"|"pcs"|null, "name": str}], '
        '"steps": [str]}\n'
        "Convert amounts to the given units (1000 g -> 1 kg, 500 ml -> 0.5 l). "
        "Use null amount and unit for ingredients without a measurable quantity. "
        "classTags describe the dish in 1-3 short labels, e.g. Chicken, Pasta, Quick, Vegetarian.\n\n" + text[:6000]
    )
    data = llm.generate_json(prompt, choice, cloud)
    if not isinstance(data, dict) or "ingredients" not in data:
        return None
    ingredients = []
    for ing in data.get("ingredients") or []:
        if not isinstance(ing, dict):
            continue
        raw = strip_markdown(str(ing.get("raw") or ing.get("name") or ""))
        name = strip_markdown(str(ing.get("name") or ing.get("raw") or ""))
        entry = {
            "raw": raw,
            "amount": ing.get("amount"),
            "unit": ing.get("unit") if ing.get("unit") in ("g", "kg", "ml", "l", "pcs") else None,
            "name": name,
        }
        # guard: the name must name a food. Unit-only leftovers ("250 g")
        # carry no per-portion factor; re-derive the entry deterministically
        # from its raw line instead of trusting the LLM numbers.
        if len(re.findall(r"[^\W\d_]", name, re.UNICODE)) < 2:
            parsed = parse_ingredient_line(raw)
            entry["name"] = (parsed or {}).get("name") or name or raw
            if parsed:
                entry["amount"], entry["unit"] = parsed["amount"], parsed["unit"]
        ingredients.append(entry)
    ingredients = expand_alternatives(ingredients)

    def _minutes(value):
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return parse_duration_minutes(value)

    total = parse_duration_minutes(data.get("totalMinutes"))
    prep, cook = _minutes(data.get("prepMinutes")), _minutes(data.get("cookMinutes"))
    if total is None and (prep is not None or cook is not None):
        total = (prep or 0) + (cook or 0) or None
    return {
        "title": str(data.get("title") or "Imported recipe"),
        "source": source,
        "base_portions": float(data.get("basePortions") or 4),
        "ingredients": ingredients,
        "steps": [str(s) for s in (data.get("steps") or [])],
        "prep_minutes": prep,
        "cook_minutes": cook,
        "total_minutes": total,
        "cuisine": data.get("cuisine") if isinstance(data.get("cuisine"), str) else None,
        "category": data.get("category") if isinstance(data.get("category"), str) else None,
        "tags": normalize_tags(data.get("tags")),
        "image_url": image_url,
    }


def import_recipe_from_text(text: str, source: str = "pasted", choice: dict | None = None,
                            cloud: dict | None = None, image_url: str | None = None) -> dict:
    result = llm_recipe(text, source, choice, cloud, image_url)
    if result is None or not result["ingredients"]:
        telemetry.record("fallback_heuristic", 0.0, reason="llm empty or unparseable")
        telemetry.set_meta(fallback="heuristic")
        return heuristic_recipe(text, source, image_url=image_url)
    return result


def og_image_url(html: str) -> str | None:
    match = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE
    )
    return match.group(1) if match and match.group(1).startswith("http") else None


def import_recipe_from_url(url: str, choice: dict | None = None, cloud: dict | None = None) -> dict:
    with telemetry.span("fetch_url"):
        response = httpx.get(url, timeout=20, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; OpenPantry/0.1)"})
        response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        with telemetry.span("schema_org"):
            schema_recipe = extract_schema_org_recipe(response.text, url)
        if schema_recipe:
            telemetry.set_meta(path="schema_org")
            return schema_recipe
        with telemetry.span("html_to_text"):
            body = html_to_text(response.text)
        telemetry.set_meta(path="llm", body_chars=len(body))
        return import_recipe_from_text(body, url, choice, cloud, og_image_url(response.text))
    return import_recipe_from_text(response.text, url, choice, cloud)


def ocr_receipt_file(path: str) -> str | None:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return None
    langs = "deu+eng"
    installed = subprocess.run([tesseract, "--list-langs"], capture_output=True, text=True)
    if installed.returncode == 0 and "deu" not in installed.stdout:
        langs = "eng"
    result = subprocess.run([tesseract, path, "stdout", "-l", langs], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout


def llm_receipt_items(ocr_text: str, choice: dict | None = None, cloud: dict | None = None) -> dict | None:
    prompt = (
        "Extract the purchased items from this grocery receipt OCR text. Respond with JSON only:\n"
        '{"store": str, "date": "YYYY-MM-DD", "total": number, '
        '"items": [{"rawName": str, "quantity": number}]}\n'
        "Skip non-product lines (totals, taxes, payment info). quantity is the number of packages.\n\n"
        + ocr_text[:6000]
    )
    data = llm.generate_json(prompt, choice, cloud)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None
    items = [
        {"raw_name": str(i.get("rawName") or ""), "quantity": float(i.get("quantity") or 1)}
        for i in data["items"]
        if isinstance(i, dict) and i.get("rawName")
    ]
    return {"store": str(data.get("store") or "Unknown"),
            "date": str(data.get("date") or ""),
            "total": float(data.get("total") or 0),
            "items": items} if items else None
