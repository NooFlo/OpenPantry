import json
import re
import shutil
import subprocess

import httpx

from . import llm

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
SPOON_UNITS = {"tsp", "teaspoon", "teaspoons", "tbsp", "tbs", "tablespoon", "tablespoons",
               "el", "tl", "prise", "pinch", "handful", "splash", "sprig", "sprigs"}
FRACTIONS = {"½": "0.5", "¼": "0.25", "¾": "0.75", "⅓": "0.33", "⅔": "0.67", "⅛": "0.125"}


def _replace_fractions(line: str) -> str:
    for frac, dec in FRACTIONS.items():
        line = re.sub(r"(\d+)\s*" + frac, lambda m, d=dec: str(float(m.group(1)) + float(d)), line)
        line = line.replace(frac, dec)
    return line
STEP_HINTS = re.compile(r"\b(minut|min\.|backen|braten|kochen|erhitzen|rühren|ruehren|geben|stir|bake|fry|boil|heat|mix|add|preheat|oven)\b", re.IGNORECASE)
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
    line = _replace_fractions(line.strip())
    match = INGREDIENT_RE.match(line)
    if not match:
        return None
    raw_amount, _range_end, raw_unit, name = match.groups()
    amount = float(raw_amount.replace(",", "."))
    name = re.sub(r"^\s*\([^)]*\)\s*", "", name).strip()
    converted = to_base_unit(amount, raw_unit)
    if converted:
        amount, unit = converted
        return {"raw": line, "amount": round(amount, 4), "unit": unit, "name": name}
    if raw_unit is None:
        return {"raw": line, "amount": amount, "unit": "pcs", "name": name}
    if raw_unit.lower() in SPOON_UNITS:
        name = re.sub(r"^\s*(?:tsp|teaspoons?|tbs|tbsps?|tablespoons?|el|tl|prise|pinch|handful|splash|sprigs?)\s+", "", name, flags=re.IGNORECASE).strip()
        return {"raw": line, "amount": None, "unit": None, "name": name}
    return {"raw": line, "amount": None, "unit": None, "name": name}


def heuristic_recipe(text: str, source: str = "pasted") -> dict:
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
        elif len(line) > 15:
            steps.append(line)
    title = "Imported recipe"
    if lines and not parse_ingredient_line(lines[0]):
        title = lines[0]
    return {
        "title": title,
        "source": source,
        "base_portions": base_portions,
        "ingredients": ingredients,
        "steps": steps,
    }


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
        parsed = parse_ingredient_line(str(raw))
        if parsed:
            ingredients.append(parsed)
        else:
            ingredients.append({"raw": str(raw), "amount": None, "unit": None, "name": str(raw)})
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
    return {
        "title": str(node.get("name") or "Imported recipe"),
        "source": url,
        "base_portions": base_portions,
        "ingredients": ingredients,
        "steps": steps,
    }


def html_to_text(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def llm_recipe(text: str, source: str, choice: dict | None = None, cloud: dict | None = None) -> dict | None:
    prompt = (
        "Extract the recipe from the following text. Respond with JSON only, in this exact shape:\n"
        '{"title": str, "basePortions": number, '
        '"ingredients": [{"raw": str, "amount": number|null, "unit": "g"|"kg"|"ml"|"l"|"pcs"|null, "name": str}], '
        '"steps": [str]}\n'
        "Convert amounts to the given units (1000 g -> 1 kg, 500 ml -> 0.5 l). "
        "Use null amount and unit for ingredients without a measurable quantity.\n\n" + text[:6000]
    )
    data = llm.generate_json(prompt, choice, cloud)
    if not isinstance(data, dict) or "ingredients" not in data:
        return None
    ingredients = []
    for ing in data.get("ingredients", []):
        if not isinstance(ing, dict):
            continue
        ingredients.append({
            "raw": str(ing.get("raw") or ing.get("name") or ""),
            "amount": ing.get("amount"),
            "unit": ing.get("unit") if ing.get("unit") in ("g", "kg", "ml", "l", "pcs") else None,
            "name": str(ing.get("name") or ing.get("raw") or ""),
        })
    return {
        "title": str(data.get("title") or "Imported recipe"),
        "source": source,
        "base_portions": float(data.get("basePortions") or 4),
        "ingredients": ingredients,
        "steps": [str(s) for s in data.get("steps", [])],
    }


def import_recipe_from_text(text: str, source: str = "pasted", choice: dict | None = None, cloud: dict | None = None) -> dict:
    return llm_recipe(text, source, choice, cloud) or heuristic_recipe(text, source)


def import_recipe_from_url(url: str, choice: dict | None = None, cloud: dict | None = None) -> dict:
    response = httpx.get(url, timeout=20, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; OpenPantry/0.1)"})
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        schema_recipe = extract_schema_org_recipe(response.text, url)
        if schema_recipe:
            return schema_recipe
        return import_recipe_from_text(html_to_text(response.text), url, choice, cloud)
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
