import logging
import io
import re
import threading
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import extract, hass, labels, mail, planning, products, repo, seed, telemetry
from .config import get_cloud_config, get_model_choice, set_model_choice
from .db import init_db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("openpantry")

frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

CAMEL_RE = re.compile(r"_([a-z])")


def camelize(data):
    if isinstance(data, list):
        return [camelize(x) for x in data]
    if isinstance(data, dict):
        return {CAMEL_RE.sub(lambda m: m.group(1).upper(), k): camelize(v) for k, v in data.items()}
    return data


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if seed.seed_if_empty():
        log.info("seeded database with demo data")
    if mail.enabled():
        import asyncio
        asyncio.create_task(mail.poll_loop())
        log.info("IMAP polling started for %s", mail.IMAP_HOST)
    yield


app = FastAPI(title="OpenPantry", lifespan=lifespan)


class ConsumeRequest(BaseModel):
    amount: float


class RestockRequest(BaseModel):
    amount: float


class BarcodeRequest(BaseModel):
    barcode: str


class BarcodeAssignRequest(BaseModel):
    barcode: str
    item_id: str | None = None
    item_name: str | None = None
    category: str | None = None
    package_size: float | None = None
    unit: str | None = None


class ConfirmLowRequest(BaseModel):
    is_low: bool


class ItemUpdateRequest(BaseModel):
    min_quantity: float | None = None
    package_size: float | None = None
    tracking_mode: str | None = None
    barcode: str | None = None


class ShoppingListRequest(BaseModel):
    amount: float


class ReceiptMatchRequest(BaseModel):
    product_name: str


class ImportRequest(BaseModel):
    kind: str
    value: str


class CookRequest(BaseModel):
    portions: float


class IngredientMatchRequest(BaseModel):
    item_name: str


class RecipeEditIngredientRequest(BaseModel):
    id: str | None = None
    raw: str


class RecipeEditRequest(BaseModel):
    title: str | None = None
    source: str | None = None
    base_portions: float | None = None
    ingredients: list[RecipeEditIngredientRequest] | None = None
    steps: list[str] | None = None


class ModelChoiceRequest(BaseModel):
    provider: str
    model: str


class SettingsRequest(BaseModel):
    receipts_model: dict | None = None
    recipes_model: dict | None = None
    cloud_base_url: str | None = None
    cloud_model: str | None = None
    cloud_api_key: str | None = None
    ha_url: str | None = None
    ha_token: str | None = None
    ha_entity: str | None = None
    planning_enabled: bool | None = None


def _settings_payload() -> dict:
    cloud = get_cloud_config()
    return {
        "receiptsModel": get_model_choice("receipts"),
        "recipesModel": get_model_choice("recipes"),
        "cloudBaseUrl": cloud["base_url"],
        "cloudModel": cloud["model"],
        "cloudKeySet": bool(cloud["api_key"]),
        "haUrl": hass.get_config()["base_url"],
        "haEntity": hass.get_config()["entity_id"],
        "haKeySet": hass.enabled(),
        "planningEnabled": (repo.get_setting("planning_enabled", "1") != "0"),
    }


@app.get("/api/settings")
def get_settings():
    return _settings_payload()


@app.put("/api/settings")
def update_settings(body: SettingsRequest):
    for task, choice in (("receipts", body.receipts_model), ("recipes", body.recipes_model)):
        if choice:
            if choice.get("provider") not in ("local", "cloud") or not choice.get("model"):
                raise HTTPException(400, f"invalid model choice for {task}")
            set_model_choice(task, choice)
    if body.cloud_base_url is not None:
        repo.set_setting("cloud_base_url", body.cloud_base_url.strip())
    if body.cloud_model is not None:
        repo.set_setting("cloud_model", body.cloud_model.strip())
    if body.cloud_api_key is not None:
        repo.set_setting("cloud_api_key", body.cloud_api_key.strip())
    if body.ha_url is not None:
        repo.set_setting("ha_url", body.ha_url.strip())
    if body.ha_token is not None:
        repo.set_setting("ha_token", body.ha_token.strip())
    if body.ha_entity is not None:
        repo.set_setting("ha_entity", body.ha_entity.strip())
    if body.ha_url is not None or body.ha_token is not None or body.ha_entity is not None:
        _push_to_ha()
    if body.planning_enabled is not None:
        repo.set_setting("planning_enabled", "1" if body.planning_enabled else "0")
    return _settings_payload()


@app.get("/api/models")
def get_models():
    return {"local": extract.llm.local_models(), "llmAvailable": extract.llm.available()}


@app.get("/api/items")
def get_items():
    return camelize(repo.list_items())


@app.post("/api/items/{item_id}/consume")
def consume(item_id: str, body: ConsumeRequest):
    item = repo.consume_item(item_id, body.amount)
    if not item:
        raise HTTPException(404, "item not found")
    _push_to_ha()
    return camelize(item)


@app.post("/api/items/{item_id}/empty")
def empty(item_id: str):
    item = repo.empty_item(item_id)
    if not item:
        raise HTTPException(404, "item not found")
    _push_to_ha()
    return camelize(item)


@app.post("/api/items/{item_id}/restock")
def restock(item_id: str, body: RestockRequest):
    if body.amount <= 0:
        raise HTTPException(400, "amount must be > 0")
    item = repo.restock_item(item_id, body.amount)
    if not item:
        raise HTTPException(404, "item not found")
    _push_to_ha()
    return camelize(item)


@app.post("/api/items/{item_id}/barcodes")
def add_item_barcode(item_id: str, body: BarcodeRequest):
    """Attach another product barcode to an item — Aldi eggs, REWE eggs, all
    deduct from the same "Eier" stock."""
    barcode = re.sub(r"\D", "", body.barcode)
    if body.barcode.strip() != barcode or not 6 <= len(barcode) <= 14:
        raise HTTPException(400, "barcode must be 6-14 digits")
    clash = repo.find_item_by_barcode(barcode)
    if clash and clash["id"] != item_id:
        raise HTTPException(409, f"barcode already used by {clash['name']}")
    item = repo.add_item_barcode(item_id, barcode)
    if not item:
        raise HTTPException(404, "item not found")
    return camelize(item)


@app.delete("/api/items/{item_id}/barcodes/{barcode}")
def remove_item_barcode(item_id: str, barcode: str):
    item = repo.remove_item_barcode(item_id, barcode)
    if not item:
        raise HTTPException(404, "item or barcode not found")
    return camelize(item)


# Ring buffer of recent scan events: the frontend polls it so a popup can open
# the moment an unknown barcode is scanned, independent of any device state.
_SCAN_EVENTS: deque = deque(maxlen=50)
_SCAN_EVENT_SEQ = [0]
_SCAN_EVENT_LOCK = threading.Lock()


def _record_scan_event(kind: str, barcode: str) -> None:
    with _SCAN_EVENT_LOCK:
        _SCAN_EVENT_SEQ[0] += 1
        _SCAN_EVENTS.append({
            "seq": _SCAN_EVENT_SEQ[0],
            "kind": kind,
            "barcode": barcode,
        })


@app.get("/api/scan/events")
def scan_events(since: int = 0):
    with _SCAN_EVENT_LOCK:
        events = [e for e in _SCAN_EVENTS if e["seq"] > since]
        current = _SCAN_EVENT_SEQ[0]
    return {"seq": current, "events": camelize(events)}


@app.post("/api/scan/barcode")
def scan_barcode(body: BarcodeRequest):
    item = repo.find_item_by_barcode(body.barcode)
    if not item:
        _record_scan_event("unknown:consume", body.barcode)
        raise HTTPException(404, "unknown barcode")
    _record_scan_event("consume", body.barcode)  # live UI refresh ping
    _push_to_ha()
    return camelize(repo.consume_item(item["id"], item["package_size"]))


# Control-code stickers for the USB scanner: scan one of these EAN-13 codes in
# the GS1 in-store reserved range (20xxxxxxxxxx — no real product can collide)
# to switch what subsequent product scans do. GET /print/control-codes renders
# them as printable barcodes; constants live in labels.py (single source of
# truth for the scanner bridge, the print page and the Epson label export).
CONTROL_CODES = labels.CONTROL_CODES


@app.post("/api/scan/purchase")
def scan_purchase(body: BarcodeRequest):
    """BOUGHT-mode scan. Known barcodes restock a package. Unknown barcodes
    auto-create the item from the Open Food Facts product (name, category,
    package size) and stock it — zero-interaction unboxing. Products OFF
    doesn't know stay unknown (404 + review popup for manual naming); an
    identical OFF product name attaches the new EAN to the existing item."""
    item = repo.find_item_by_barcode(body.barcode)
    if not item:
        product = products.product_info(body.barcode)
        if not product:
            _record_scan_event("unknown:bought", body.barcode)
            raise HTTPException(404, "unknown barcode")
        existing = repo.find_item_by_name(product["name"])
        if existing:
            item = repo.add_item_barcode(existing["id"], body.barcode) or existing
        else:
            amount, unit = products.parse_quantity(product.get("quantity")) or (None, None)
            item = repo.create_item(
                name=product["name"],
                category=products.guess_category(product.get("categories")),
                unit=unit or "pcs",
                package_size=amount or 1.0,
                barcode=body.barcode,
                tracking_mode="qty",  # count packages: each scan adds +1
            )
    _record_scan_event("bought", body.barcode)  # live UI refresh ping
    _push_to_ha()
    restocked = repo.restock_item(item["id"], item["package_size"] or 1)
    return camelize(restocked or item)


@app.post("/api/scan/empty")
def scan_empty(body: BarcodeRequest):
    item = repo.find_item_by_barcode(body.barcode)
    if not item:
        _record_scan_event("unknown:empty", body.barcode)
        raise HTTPException(404, "unknown barcode")
    item = repo.empty_item(item["id"])
    _record_scan_event("empty", body.barcode)  # live UI refresh ping
    _push_to_ha()
    return camelize(item)


@app.get("/print/control-codes", response_class=HTMLResponse)
def print_control_codes():
    try:
        import barcode as barcode_lib
        from barcode.writer import SVGWriter

        import qrcode
        from qrcode.image.svg import SvgPathImage

        def qr_svg(content):
            buffer = io.BytesIO()
            qrcode.make(content, image_factory=SvgPathImage, box_size=8).save(buffer)
            svg = buffer.getvalue().decode()
            return svg.replace("<svg", '<svg style="background:#fff"', 1)

        ean_cards = []
        qr_cards = []
        for action, meta in CONTROL_CODES.items():
            svg = barcode_lib.EAN13(meta["code"], writer=SVGWriter()).render()
            hint = f"{meta['code']} — {meta['hint']}"
            ean_cards.append(
                f"<div class='card'><h2>{meta['label']}</h2>{svg.decode()}"
                f"<p class='digits'>{meta['code']}</p><p class='hint'>{hint}</p></div>"
            )
            qr_cards.append(
                f"<div class='card'><h2>{meta['label']}</h2>{qr_svg(meta['code'])}"
                f"<p class='digits'>{meta['code']}</p><p class='hint'>{hint}</p></div>"
            )
        body = (
            "<div class='cards'>" + "\n".join(ean_cards) + "</div>"
            "<h3>QR versions (for 2D-only scanners)</h3>"
            "<div class='cards'>" + "\n".join(qr_cards) + "</div>"
        )
        err = ""
    except Exception as e:  # noqa: BLE001
        body, err = "", f"<p>Rendering failed: {e}</p>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>OpenPantry control codes</title>
<style>
body {{ font-family: -apple-system, sans-serif; background: #fff; color: #111; max-width: 780px; margin: 24px auto; }}
h1 {{ font-size: 22px; }}
.cards {{ display: flex; gap: 24px; flex-wrap: wrap; }}
.card {{ border: 2px solid #111; border-radius: 12px; padding: 18px 22px; text-align: center; page-break-inside: avoid; }}
.card h2 {{ margin: 0 0 10px; letter-spacing: 1px; }}
.card svg {{ width: 210px; }}
.digits {{ font-family: monospace; font-size: 15px; margin: 6px 0 2px; }}
.hint {{ font-size: 13px; color: #555; margin: 4px 0 0; max-width: 230px; }}
ol {{ font-size: 14px; line-height: 1.5; }}
@media print {{ body {{ margin: 0; }} }}
</style></head><body>
<h1>OpenPantry scanner control codes</h1>
<p class="hint">EAN barcodes below, QR versions further down. Both encode the same
digits — print whichever your scanner reads and keep it next to the scanner.</p>
{body}
{err}
<h3>How to use</h3>
<ol>
<li>Print this page (sticker paper or card stock, laminated works best) and keep it next to the scanner.</li>
<li>Scan one control code to switch the scanner mode — it stays active until another control code is scanned.</li>
<li><b>Unpacking groceries:</b> scan BOUGHT once, then scan each product. Unknown products land in the review queue with their Open Food Facts data.</li>
<li><b>Throwing packaging away:</b> scan EMPTY, then the product — stock goes to zero and it's re-ordered.</li>
<li>Scan CONSUME to return to the default (package used up/cooking).</li>
</ol>
</body></html>"""


def _clean_barcode(raw: str) -> str:
    barcode = re.sub(r"\D", "", raw)
    if not 6 <= len(barcode) <= 14:
        raise HTTPException(400, "invalid barcode")
    return barcode


@app.post("/api/barcode/lookup")
def barcode_lookup(body: BarcodeRequest):
    """Scan preprocessing: a known barcode reports its item; an unknown one is
    looked up on Open Food Facts (and its sister projects), cached, and paired
    with generic-catalog suggestions for the review queue."""
    barcode = _clean_barcode(body.barcode)
    item = repo.find_item_by_barcode(barcode)
    if item:
        return {"status": "known", "item": camelize(item)}
    product = products.product_info(barcode)
    if not product:
        return {"status": "not_found", "barcode": barcode}
    return {
        "status": "unknown",
        "product": camelize(product),
        "suggestions": camelize(products.suggest_items(product)),
    }


@app.get("/api/barcode/pending")
def barcode_pending():
    return {"barcodes": camelize(products.pending_barcodes())}


@app.delete("/api/barcode/pending/{barcode}")
def discard_pending_barcode(barcode: str):
    """Remove a queue entry for good: unwanted scans vanish everywhere."""
    if not products.discard_cached(barcode):
        raise HTTPException(404, "barcode not in the review queue")
    return {"discarded": barcode}


@app.post("/api/barcode/assign")
def barcode_assign(body: BarcodeAssignRequest):
    """Confirm a barcode mapping: attach it to an existing item, or register a
    new catalog item (package size defaults from the cached OFF product)."""
    barcode = _clean_barcode(body.barcode)
    if not body.item_id and not (body.item_name or "").strip():
        raise HTTPException(400, "item_id or item_name is required")
    item = None
    if body.item_id:
        item = repo.set_item_barcode(body.item_id, barcode)
        if not item:
            raise HTTPException(404, "item not found")
    else:
        package_size, unit = body.package_size, body.unit
        if package_size is None or unit is None:
            product = products.product_info(barcode) or {}
            parsed = products.parse_quantity(product.get("quantity"))
            if package_size is None:
                package_size = parsed[0] if parsed else 1.0
            if unit is None:
                unit = parsed[1] if parsed else "pcs"
        existing = repo.find_item_by_name(body.item_name.strip())
        if existing:
            item = repo.set_item_barcode(existing["id"], barcode) or repo.get_item(existing["id"])
        else:
            item = repo.create_item(
                name=body.item_name.strip(),
                category=body.category or "Pantry",
                unit=unit or "pcs",
                package_size=package_size or 1.0,
                barcode=barcode,
                tracking_mode="qty",  # count packages: scans add +1 each
            )
    return camelize(item)


@app.post("/api/items/{item_id}/update")
def update_item(item_id: str, body: ItemUpdateRequest):
    if body.min_quantity is not None and body.min_quantity < 0:
        raise HTTPException(400, "min_quantity must be >= 0")
    if body.package_size is not None and body.package_size <= 0:
        raise HTTPException(400, "package_size must be > 0")
    if body.tracking_mode is not None and body.tracking_mode not in ("binary", "qty"):
        raise HTTPException(400, "tracking_mode must be 'binary' or 'qty'")
    new_barcode = None
    if body.barcode is not None:
        cleaned = re.sub(r"\D", "", body.barcode)
        if body.barcode.strip():
            if len(cleaned) != len(body.barcode.strip()) or not 6 <= len(cleaned) <= 14:
                raise HTTPException(400, "barcode must be 6-14 digits")
            clash = repo.find_item_by_barcode(cleaned)
            if clash and clash["id"] != item_id:
                raise HTTPException(409, f"barcode already used by {clash['name']}")
            new_barcode = cleaned
        # an empty barcode clears the mapping
    item = repo.update_item(item_id, body.min_quantity, body.package_size,
                            body.tracking_mode, barcode=new_barcode)
    if not item:
        raise HTTPException(404, "item not found")
    return camelize(item)


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    item = repo.delete_item(item_id)
    if not item:
        raise HTTPException(404, "item not found")
    _push_to_ha()
    return camelize(item)


@app.post("/api/items/{item_id}/confirm-low")
def confirm_low(item_id: str, body: ConfirmLowRequest):
    item = repo.confirm_low(item_id, body.is_low)
    if not item:
        raise HTTPException(404, "item not found")
    _push_to_ha()
    return camelize(item)


@app.get("/api/receipts")
def get_receipts():
    return camelize(repo.list_receipts())


@app.post("/api/receipts/{receipt_id}/items/{item_id}/match")
def match_receipt_item(receipt_id: str, item_id: str, body: ReceiptMatchRequest):
    if not repo.get_receipt(receipt_id):
        raise HTTPException(404, "receipt not found")
    item = repo.find_item_by_name(body.product_name)
    if not item:
        item = repo.create_item(name=body.product_name)
    receipt = repo.match_receipt_item(receipt_id, item_id, item["name"])
    _push_to_ha()
    return camelize(receipt)


@app.get("/api/recipes")
def get_recipes():
    return camelize(repo.list_recipes())


@app.post("/api/recipes/import")
def import_recipe(body: ImportRequest):
    trace = telemetry.start_trace("recipe_import")
    telemetry.set_meta(kind=body.kind, value=body.value[:100], input_chars=len(body.value))
    try:
        choice = get_model_choice("recipes")
        cloud = get_cloud_config()
        if body.kind == "link":
            data = extract.import_recipe_from_url(body.value, choice, cloud)
        elif body.kind == "text":
            data = extract.import_recipe_from_text(body.value, "pasted", choice, cloud)
        else:
            trace.finish("bad_kind")
            raise HTTPException(400, "kind must be 'link' or 'text'")
    except httpx.HTTPError:
        trace.finish("fetch_failed")
        raise HTTPException(502, "could not fetch the recipe URL")
    if not data["ingredients"]:
        trace.finish("no_ingredients")
        raise HTTPException(422, "could not extract any ingredients")
    with telemetry.span("match_items"):
        result = camelize(_create_recipe_with_matches(data, choice, cloud))
    trace.finish("ok")
    return result


@app.get("/api/recipes/import/traces")
def recipe_import_traces():
    return telemetry.recent_traces()


def _recipe_meta(data: dict) -> dict:
    keys = ("prep_minutes", "cook_minutes", "total_minutes", "cuisine", "category", "tags", "image_url")
    return {k: data[k] for k in keys if data.get(k) is not None and data.get(k) != []}


def _canonical_names(data: dict, choice: dict | None, cloud: dict | None) -> dict[str, str]:
    """Post-processed ("spring onions, finely sliced") -> raw ("spring onions").

    Deterministic stripping first; the LLM only sees leftovers that still carry
    preparation hints, and its output is guarded (see llm.canonicalize_names).
    """
    names = [extract.base_ingredient_name(ing["name"]) for ing in data["ingredients"]]
    residual = [n for n in dict.fromkeys(names) if extract.needs_name_canonicalization(n)]
    if not residual:
        return {}
    with telemetry.span("canonicalize_names", count=len(residual)):
        mapping = extract.llm.canonicalize_names(residual, choice, cloud)
    return {k: v for k, v in (mapping or {}).items() if v}


# Staples every kitchen has: never stock-tracked, always considered available
ALWAYS_AVAILABLE = {"water", "wasser"}


def _ingredient_entry(ing: dict, canon: dict[str, str]) -> dict:
    name = extract.base_ingredient_name(ing["name"])
    name = canon.get(name, name)
    entry = {"raw": ing["raw"], "amount": ing.get("amount"), "unit": ing.get("unit"),
             "tracked": True, "suggestion": None}
    if ing.get("alt_group"):
        entry["alt_group"] = ing["alt_group"]
    if name.lower() in ALWAYS_AVAILABLE:
        entry["tracked"] = False
        return entry
    item = repo.find_item_by_name(name)
    if item:
        entry["item_id"] = item["id"]
    else:
        match = repo.best_name_match(name)
        entry["suggestion"] = match["name"] if match else name
    return entry


def _create_recipe_with_matches(data: dict, choice: dict | None = None, cloud: dict | None = None) -> dict:
    canon = _canonical_names(data, choice, cloud)
    ingredients = [_ingredient_entry(ing, canon) for ing in data["ingredients"]]
    with telemetry.span("step_links", steps=len(data["steps"])):
        links = extract.link_ingredients_in_steps(data["steps"], ingredients, choice, cloud)
    recipe = repo.create_recipe(data["title"], data["source"], data["base_portions"],
                                ingredients, data["steps"], _recipe_meta(data))
    if links:
        return repo.set_step_ingredient_links(recipe["id"], links)
    return recipe


@app.post("/api/recipes/{recipe_id}/refresh")
def refresh_recipe(recipe_id: str):
    recipe = _get_recipe_or_404(recipe_id)
    if not recipe["source"].startswith("http"):
        raise HTTPException(400, "only recipes imported from a link can be refreshed")
    trace = telemetry.start_trace("recipe_refresh")
    telemetry.set_meta(recipe_id=recipe_id, value=recipe["source"][:100])
    try:
        choice = get_model_choice("recipes")
        cloud = get_cloud_config()
        data = extract.import_recipe_from_url(recipe["source"], choice, cloud)
    except httpx.HTTPError:
        trace.finish("fetch_failed")
        raise HTTPException(502, "could not fetch the recipe URL")
    if not data["ingredients"]:
        trace.finish("no_ingredients")
        raise HTTPException(422, "could not extract any ingredients")
    canon = _canonical_names(data, choice, cloud)
    ingredients = [_ingredient_entry(ing, canon) for ing in data["ingredients"]]
    with telemetry.span("step_links", steps=len(data["steps"])):
        links = extract.link_ingredients_in_steps(data["steps"], ingredients, choice, cloud)
    result = repo.replace_recipe(recipe_id, data["title"], data["source"],
                                  data["base_portions"], ingredients, data["steps"], _recipe_meta(data))
    if links:
        result = repo.set_step_ingredient_links(recipe_id, links)
    trace.finish("ok")
    return camelize(result)


def _get_recipe_or_404(recipe_id: str) -> dict:
    recipe = repo.get_recipe(recipe_id)
    if not recipe:
        raise HTTPException(404, "recipe not found")
    return recipe


@app.post("/api/recipes/{recipe_id}/cook")
def cook(recipe_id: str, body: CookRequest):
    recipe = _get_recipe_or_404(recipe_id)
    result = camelize(repo.cook_recipe(recipe, body.portions))
    _push_to_ha()
    return result


@app.post("/api/recipes/{recipe_id}/add-missing")
def add_missing(recipe_id: str, body: CookRequest):
    recipe = _get_recipe_or_404(recipe_id)
    items_by_id = {i["id"]: i for i in repo.list_items()}
    result = camelize(repo.add_missing_to_shopping_list(recipe, items_by_id, body.portions))
    _push_to_ha()
    return result


@app.post("/api/recipes/{recipe_id}/ingredients/{ingredient_id}/match")
def match_ingredient(recipe_id: str, ingredient_id: str, body: IngredientMatchRequest):
    recipe = _get_recipe_or_404(recipe_id)
    ingredient = next((i for i in recipe["ingredients"] if i["id"] == ingredient_id), None)
    if not ingredient:
        raise HTTPException(404, "ingredient not found")
    item = repo.find_item_by_name(body.item_name)
    if not item:
        item = repo.create_item(name=body.item_name, unit=ingredient.get("unit") or "pcs")
    amount = ingredient["amount"]
    if amount is None:
        numbers = re.findall(r"\d+(?:[.,]\d+)?", ingredient["raw"])
        amount = float(numbers[0].replace(",", ".")) if numbers else 1.0
    return camelize(repo.match_recipe_ingredient(recipe_id, ingredient_id, item["id"], amount))


@app.post("/api/recipes/{recipe_id}/ingredients/{ingredient_id}/select")
def select_ingredient(recipe_id: str, ingredient_id: str):
    """Pick one option of an "and/or" alternative group (e.g. basmati rice
    or naan): the pick is what goes on the shopping list when it's missing."""
    if not repo.get_recipe(recipe_id):
        raise HTTPException(404, "recipe not found")
    recipe = repo.select_recipe_ingredient(recipe_id, ingredient_id)
    if not recipe:
        raise HTTPException(404, "ingredient not found")
    return camelize(recipe)


def _edited_ingredients(recipe: dict, edits: list) -> list[dict]:
    """Rebuild the ingredient list from an edit form:
    - lines whose raw text is unchanged keep their item match, tracking
      flag and and/or alternative group untouched
    - changed or new lines re-run the deterministic part of the import
      matching pipeline (parsing, amount extraction, alternative
      splitting, name matching and suggestions)
    """
    old = {i["id"]: i for i in recipe["ingredients"]}
    entries: list[dict] = []
    for edit in edits:
        raw = extract.strip_markdown((edit.raw or "").strip())
        if not raw:
            continue
        prior = old.get(edit.id) if edit.id else None
        if prior and prior["raw"] == raw:
            entries.append({
                "raw": prior["raw"], "amount": prior["amount"], "unit": prior.get("unit"),
                "item_id": prior.get("item_id"), "tracked": bool(prior["tracked"]),
                "suggestion": prior.get("suggestion"), "alt_group": prior.get("alt_group"),
                "selected": bool(prior["selected"]),
            })
            continue
        parsed = extract.parse_ingredient_line(raw)
        base = parsed or {"raw": raw, "amount": None, "unit": None, "name": raw}
        for alt in extract.expand_alternatives([base]):
            entries.append(_ingredient_entry(alt, {}))
    # a group reduced to a single option is a plain line again
    counts: dict[str, int] = {}
    for entry in entries:
        if entry.get("alt_group"):
            counts[entry["alt_group"]] = counts.get(entry["alt_group"], 0) + 1
    for entry in entries:
        if entry.get("alt_group") and counts[entry["alt_group"]] < 2:
            entry["alt_group"] = None
    return entries


@app.patch("/api/recipes/{recipe_id}")
def edit_recipe(recipe_id: str, body: RecipeEditRequest):
    """Manual recipe edit: title, source, base portions, ingredient lines
    and steps. Unchanged ingredient lines keep their pantry matches."""
    recipe = _get_recipe_or_404(recipe_id)
    if body.title is not None and not body.title.strip():
        raise HTTPException(422, "title must not be empty")
    if body.base_portions is not None and body.base_portions <= 0:
        raise HTTPException(422, "base portions must be a positive number")
    ingredients = _edited_ingredients(recipe, body.ingredients) if body.ingredients is not None else None
    title = body.title.strip() if body.title is not None else None
    updated = repo.update_recipe(recipe_id, title, body.source, body.base_portions,
                                  body.steps, ingredients)
    if body.steps is not None or ingredients is not None:
        # step or ingredient lines changed: re-derive the (qty) mention spans
        choice = get_model_choice("recipes")
        cloud = get_cloud_config()
        links = extract.link_ingredients_in_steps(updated["steps"], updated["ingredients"],
                                                 choice, cloud)
        updated = repo.set_step_ingredient_links(recipe_id, links)
    return camelize(updated)


@app.delete("/api/recipes/{recipe_id}")
def delete_recipe(recipe_id: str):
    if not repo.delete_recipe(recipe_id):
        raise HTTPException(404, "recipe not found")
    return {"deleted": True}


@app.get("/api/shopping-list")
def get_shopping_list():
    return camelize(repo.list_shopping_list())


def _push_to_ha():
    if not hass.enabled():
        return False
    return hass.sync(repo.list_shopping_list())


@app.post("/api/shopping-list/push")
def push_shopping_list():
    return {"pushed": _push_to_ha()}


@app.post("/api/shopping-list/{item_id}")
def add_to_list(item_id: str, body: ShoppingListRequest):
    try:
        result = camelize(repo.add_to_shopping_list(item_id, body.amount))
        _push_to_ha()
        return result
    except KeyError:
        raise HTTPException(404, "item not found")


@app.delete("/api/shopping-list/{item_id}")
def remove_from_list(item_id: str):
    result = camelize(repo.remove_from_shopping_list(item_id))
    _push_to_ha()
    return result


@app.get("/c/{item_id}", response_class=HTMLResponse)
def consume_landing(item_id: str):
    item = repo.get_item(item_id)
    if not item:
        raise HTTPException(404, "item not found")
    binary = item["tracking_mode"] == "binary"
    stock_line = ("In stock" if item["quantity"] > 0 else "Not in stock") if binary \
        else f"{item['quantity']} {item['unit']} in stock"
    button_line = "Mark as used up" if binary \
        else f"Used up one package ({item['package_size']} {item['unit']})"
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenPantry</title>
<style>
body {{ font-family: -apple-system, sans-serif; display: grid; place-items: center; min-height: 100dvh; margin: 0; background: #0f0f0e; color: #f5f4f2; }}
button {{ background: #ff7000; color: #fff; border: none; border-radius: 14px; padding: 16px 32px; font-size: 17px; font-weight: 600; }}
p {{ color: #a3a09a; }}
#done {{ color: #6cbf6f; font-weight: 600; }}
</style>
</head>
<body>
<div style="text-align:center">
<h1>{item["name"]}</h1>
<p>{stock_line}</p>
<button onclick="consume()">{button_line}</button>
<p id="done"></p>
</div>
<script>
async function consume() {{
  const r = await fetch('/api/items/{item_id}/consume', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ amount: {item["package_size"]} }})
  }});
  document.getElementById('done').textContent = r.ok ? 'Recorded.' : 'Failed.';
}}
</script>
</body>
</html>"""


@app.get("/tag/{item_id}/buy", response_class=PlainTextResponse)
def tag_buy(item_id: str):
    """Plain-GET tag endpoint: browsers, QR scans and Shortcuts can hit
    it directly; adds one package to the shopping list."""
    item = repo.get_item(item_id)
    if not item:
        raise HTTPException(404, "item not found")
    amount = item["package_size"] or 1
    repo.add_to_shopping_list(item_id, amount)
    _push_to_ha()
    return f"{item['name']}: {amount} {item['unit']} added to the shopping list."


@app.get("/tag/{item_id}/empty", response_class=PlainTextResponse)
def tag_empty(item_id: str):
    """Plain-GET tag endpoint for an empty container: zeroes the stock
    and puts the item on the shopping list."""
    item = repo.empty_item(item_id)
    if not item:
        raise HTTPException(404, "item not found")
    _push_to_ha()
    return f"{item['name']}: empty — added to the shopping list."


@app.get("/api/labels/item/{item_id}/png")
def item_label_png(item_id: str, request: Request, tape: int = 24):
    """Label preview PNG: QR (consume link) + name (+ product barcode on 24 mm)."""
    item = repo.get_item(item_id)
    if not item:
        raise HTTPException(404, "item not found")
    image = labels.item_label(item, str(request.base_url), tape)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@app.get("/api/labels/items.lemd")
def item_labels_lemd(request: Request, ids: str, tape: int = 24):
    """Epson Label Editor mobile strip for inventory labels ('Ids' comma-
    separated); separated by dashed cut marks, imported in the Epson app."""
    images = []
    for item_id in [part.strip() for part in ids.split(",") if part.strip()]:
        item = repo.get_item(item_id)
        if not item:
            raise HTTPException(404, f"item not found: {item_id}")
        images.append(labels.item_label(item, str(request.base_url), tape))
    if not images:
        raise HTTPException(400, "no item ids given")
    return _lemd_response(labels.generate_lemd(images, tape), "openpantry-labels.lemd")


@app.get("/api/labels/control-codes.lemd")
def control_codes_lemd(request: Request, tape: int = 24, format: str = "ean"):
    """Epson strip with the three scanner control-code stickers; format=qr
    renders QR codes of the same digits (2D-only scanners)."""
    images = [img for img, _, _ in labels.control_code_labels(tape, qr=format == "qr")]
    if not images:
        raise HTTPException(500, "control codes could not be rendered")
    return _lemd_response(labels.generate_lemd(images, tape), "openpantry-control-codes.lemd")


class ItemScanRequest(BaseModel):
    item_id: str


@app.post("/api/scan/item")
def scan_item(body: ItemScanRequest):
    """Item-label QR scanned by the USB wedge: it types the label URL
    (/c/<item>), the bridge extracts the item and consumes one package —
    the same action as the landing page's button."""
    item = repo.get_item(body.item_id)
    if not item:
        raise HTTPException(404, "item not found")
    _push_to_ha()
    return camelize(repo.consume_item(item["id"], item["package_size"]))


def _lemd_response(payload: str, filename: str) -> Response:
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/health")
def health():
    return {"ok": True, "llm": extract.llm.available(), "mail": mail.enabled()}


class PlanPersonRequest(BaseModel):
    name: str


class PlanMealRequest(BaseModel):
    week: str
    day: int
    meal: str
    person_ids: list[str] = []


class PlanMealPersonRequest(BaseModel):
    person_id: str


class PlanFillRequest(BaseModel):
    recipe_id: str | None = None
    prepared_id: str | None = None
    portions: float = 1
    prep_multiplier: float = 0
    # fill-level target (drop onto a divided per-person field)
    person_id: str | None = None
    # persons who eat this meal; auto-attached if missing (whole-field drop)
    person_ids: list[str] = []


class PlanPreparedRequest(BaseModel):
    name: str
    portions: float = 1


@app.get("/api/plan")
def get_plan(week: str):
    try:
        return camelize(planning.plan_payload(week))
    except ValueError:
        raise HTTPException(400, "week must be an ISO date")


@app.post("/api/plan/persons")
def add_plan_person(body: PlanPersonRequest):
    try:
        return camelize(planning.add_person(body.name))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/plan/persons/{person_id}")
def remove_plan_person(person_id: str):
    return camelize(planning.remove_person(person_id))


@app.post("/api/plan/meals")
def add_plan_meal(body: PlanMealRequest):
    try:
        return camelize(
            planning.add_meal(body.week, body.day, body.meal, body.person_ids)
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/plan/meals/{meal_id}/persons")
def toggle_plan_meal_person(meal_id: str, body: PlanMealPersonRequest):
    try:
        return camelize(planning.toggle_meal_person(meal_id, body.person_id))
    except LookupError:
        raise HTTPException(404, "meal not found")


@app.delete("/api/plan/meals/{meal_id}")
def remove_plan_meal(meal_id: str):
    try:
        return camelize(planning.remove_meal(meal_id))
    except LookupError:
        raise HTTPException(404, "meal not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/plan/meals/{meal_id}/fills")
def add_plan_fill(meal_id: str, body: PlanFillRequest):
    try:
        return camelize(
            planning.add_fill(
                meal_id,
                recipe_id=body.recipe_id,
                prepared_id=body.prepared_id,
                portions=body.portions,
                prep_multiplier=body.prep_multiplier,
                person_id=body.person_id,
                person_ids=body.person_ids,
            )
        )
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/plan/fills/{fill_id}")
def remove_plan_fill(fill_id: str):
    try:
        return camelize(planning.remove_fill(fill_id))
    except LookupError:
        raise HTTPException(404, "fill not found")


@app.post("/api/plan/prepared")
def add_plan_prepared(body: PlanPreparedRequest):
    try:
        return camelize(planning.add_prepared(body.name, body.portions))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/plan/prepared/{prepared_id}")
def remove_plan_prepared(prepared_id: str):
    return camelize(planning.remove_prepared(prepared_id))


@app.get("/api/plan/{week}/shopping-list")
def plan_shopping_list(week: str):
    try:
        return camelize(planning.week_shopping_list(week))
    except ValueError:
        raise HTTPException(400, "week must be an ISO date")


@app.post("/api/plan/{week}/shopping-list/push")
def push_plan_shopping_list(week: str):
    try:
        result = camelize(planning.push_week_shopping_list(week))
    except ValueError:
        raise HTTPException(400, "week must be an ISO date")
    _push_to_ha()
    return result


if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def index():
        return "<html><body><p>OpenPantry backend running. Build the frontend or see /docs.</p></body></html>"
