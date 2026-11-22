import logging
import io
import re
import socket
import threading
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import catalog, extract, hass, labels, mail, planning, products, repo, seed, telemetry
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
    buy_amount: float | None = None
    auto_restock: bool | None = None
    barcode: str | None = None
    name: str | None = None
    category: str | None = None
    concept_id: str | None = None
    generic_name: str | None = None


class ItemCreateRequest(BaseModel):
    name: str
    category: str | None = None
    unit: str | None = None
    quantity: float | None = None
    min_quantity: float | None = None
    package_size: float | None = None
    buy_amount: float | None = None
    tracking_mode: str | None = None
    barcode: str | None = None
    concept_id: str | None = None
    generic_name: str | None = None


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


class MissingMergeRequest(BaseModel):
    key: str
    item_id: str
    # what the merged rows should be called in the recipes ("fresh ginger");
    # falls back to the item name when absent
    name: str | None = None


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
    # Base URL baked into label QRs / consume links (phones must reach it).
    # Empty = auto-detect the server's LAN IP.
    label_base_url: str | None = None


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
        "labelBaseUrl": repo.get_setting("label_base_url") or "",
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
    if body.label_base_url is not None:
        url = body.label_base_url.strip().rstrip("/")
        if url and not re.match(r"https?://[\w.\-]+(\:\d+)?(/.*)?$", url):
            raise HTTPException(400, "label base URL must be http(s)://host[:port]")
        repo.set_setting("label_base_url", url)
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


def _record_scan_event(kind: str, barcode: str, item: dict | None = None) -> None:
    """Ping the live UI (ring) and persist the scan (table): the recent-scans
    view survives restarts even when the in-memory ring is wiped."""
    with _SCAN_EVENT_LOCK:
        _SCAN_EVENT_SEQ[0] += 1
        _SCAN_EVENTS.append({
            "seq": _SCAN_EVENT_SEQ[0],
            "kind": kind,
            "barcode": barcode,
        })
    if not kind.startswith("unknown"):
        repo.record_scan(kind, barcode, item)
    else:
        repo.record_scan(kind, barcode, None)


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
        products.product_info(body.barcode)  # caches the OFF miss for the review queue
        products.record_scan_intent(body.barcode, "consume")
        _record_scan_event("unknown:consume", body.barcode)
        raise HTTPException(404, "unknown barcode")
    consumed = repo.consume_item(item["id"], item["package_size"])
    _record_scan_event("consume", body.barcode, consumed or item)  # live UI refresh ping
    _push_to_ha()
    return camelize(consumed or item)


# Control-code stickers for the USB scanner: scan one of these EAN-13 codes in
# the GS1 in-store reserved range (20xxxxxxxxxx — no real product can collide)
# to switch what subsequent product scans do. Two codes only: BOUGHT switches
# to restock mode, TRASH switches back to the default consume mode (scan
# deducts one package) — trash *is* consume. GET /print/control-codes renders
# them as printable barcodes; constants live in labels.py (single source of
# truth for the scanner bridge, the print page, the Epson label export and the
# editable sticker designs).
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
            products.record_scan_intent(body.barcode, "bought")
            _record_scan_event("unknown:bought", body.barcode)
            raise HTTPException(404, "unknown barcode")
        existing = repo.find_item_by_name(product["name"])
        if not existing:
            # concept-level reuse: another brand of the same generic food
            # ("Kichererbsen" vs "CECI SOTTOVUOTO") stocks the SAME generic
            # item instead of spawning a duplicate
            concept = catalog.resolve_item_concept({"name": product["name"]})
            if concept:
                same_concept = [i for i in repo.list_items()
                                if catalog.resolve_item_concept(i) == concept]
                if same_concept:
                    existing = same_concept[0]
        if existing:
            item = repo.add_item_barcode(existing["id"], body.barcode) or existing
        else:
            amount, unit = products.parse_quantity(product.get("quantity")) or (None, None)
            # the concept family is the better categorizer than OFF tags
            category = None
            concept = catalog.resolve_item_concept({"name": product["name"]})
            if concept:
                category = catalog.FAMILY_DEFAULT_CATEGORY.get(
                    catalog.CONCEPTS[concept]["family"])
            item = repo.create_item(
                name=product["name"],
                category=category or products.guess_category(product.get("categories")),
                unit=unit or "pcs",
                package_size=amount or 1.0,
                barcode=body.barcode,
                tracking_mode="qty",  # count packages: each scan adds +1
            )
    _push_to_ha()
    restocked = repo.restock_item(item["id"], item["package_size"] or 1)
    _record_scan_event("bought", body.barcode, restocked or item)  # live UI refresh ping
    return camelize(restocked or item)


@app.post("/api/scan/empty")
def scan_empty(body: BarcodeRequest):
    """Kept for older wedge-bridge configs: TRASH *is* consume now (scan
    deducts one package), so this endpoint behaves exactly like the
    default scan. Point the Rock5 bridge's trash mode at /api/scan/barcode
    and this becomes dead code."""
    item = repo.find_item_by_barcode(body.barcode)
    if not item:
        products.product_info(body.barcode)  # caches the OFF miss for the review queue
        products.record_scan_intent(body.barcode, "consume")
        _record_scan_event("unknown:consume", body.barcode)
        raise HTTPException(404, "unknown barcode")
    consumed = repo.consume_item(item["id"], item["package_size"])
    _record_scan_event("consume", body.barcode, consumed or item)  # live UI refresh ping
    _push_to_ha()
    return camelize(consumed or item)


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
<li><b>Throwing packaging away:</b> scan TRASH, then the products — each scan deducts one package (the same as the default mode).</li>
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


def _last_scan_intent(barcode: str) -> str | None:
    """Scanned-unknown intent, persisted in the barcode cache (survives
    restarts): 'bought' -> naming stocks a package, 'consume' -> the item
    starts empty. Cleared once the naming consumed it."""
    return products.scan_intent(barcode)


@app.post("/api/barcode/assign")
def barcode_assign(body: BarcodeAssignRequest):
    """Confirm a barcode mapping: attach it to an existing item, or register a
    new catalog item (package size defaults from the cached OFF product).
    A barcode whose last scan was a purchase scan is stocked with one package,
    so naming an unknown product completes the original BOUGHT scan."""
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
    if _last_scan_intent(barcode) == "bought":
        products.clear_scan_intent(barcode)  # naming consumed the scan
        item = repo.restock_item(item["id"], item["package_size"] or 1) or item
        _record_scan_event("bought", barcode)  # live UI refresh ping
    else:
        products.clear_scan_intent(barcode)
    _push_to_ha()
    return camelize(item)


@app.post("/api/items")
def create_item(body: ItemCreateRequest):
    """Manual item creation with every attribute. The concept tag comes
    from an explicit (validated) concept_id or is resolved from the name;
    a user-picked category always wins over the family default. A
    quantity > 1 switches to quantity tracking unless tracking_mode is
    set explicitly."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(422, "name must not be empty")
    if body.unit is not None and body.unit not in ("g", "kg", "ml", "l", "pcs"):
        raise HTTPException(400, "unit must be one of g, kg, ml, l, pcs")
    if body.tracking_mode is not None and body.tracking_mode not in ("binary", "qty"):
        raise HTTPException(400, "tracking_mode must be 'binary' or 'qty'")
    if repo.find_item_by_name(name):
        raise HTTPException(409, "an item with that name already exists")
    barcode = None
    if body.barcode and body.barcode.strip():
        barcode = re.sub(r"\D", "", body.barcode)
        if not 6 <= len(barcode) <= 14:
            raise HTTPException(400, "barcode must be 6-14 digits")
        clash = repo.find_item_by_barcode(barcode)
        if clash:
            raise HTTPException(409, f"barcode already used by {clash['name']}")
    concept = body.concept_id
    if concept and concept not in catalog.CONCEPTS:
        raise HTTPException(400, f"unknown concept {concept}")
    if not concept:
        concept = catalog.resolve_item_concept({"name": name})
    quantity = max(0.0, body.quantity or 0.0)
    tracking = body.tracking_mode
    if tracking is None and quantity > 0:
        tracking = "qty" if quantity > 1 else "binary"
    if quantity == 0:
        tracking = tracking or "binary"
    if (body.min_quantity or 0) > 0 and tracking == "binary":
        raise HTTPException(400, "binary items cannot carry an alarm threshold; use quantity tracking")
    try:
        item = repo.create_item(
            name=name,
            category=(body.category or "Pantry").strip() or "Pantry",
            unit=body.unit or "pcs",
            package_size=max(0.0001, body.package_size or 1.0),
            barcode=barcode,
            tracking_mode=tracking or "binary",
            concept_id=concept,
            category_explicit=body.category is not None,
            quantity=quantity,
            generic_name=body.generic_name,
        )
    except ValueError as error:
        raise HTTPException(409, str(error))
    with repo.get_db() as db:
        if body.min_quantity or body.buy_amount:
            db.execute(
                "UPDATE items SET min_quantity = COALESCE(?, min_quantity),"
                " buy_amount = COALESCE(?, buy_amount) WHERE id = ?",
                (body.min_quantity, body.buy_amount, item["id"]))
    return camelize(repo.get_item(item["id"]))


@app.post("/api/items/{item_id}/update")
def update_item(item_id: str, body: ItemUpdateRequest):
    if body.min_quantity is not None and body.min_quantity < 0:
        raise HTTPException(400, "min_quantity must be >= 0")
    if body.package_size is not None and body.package_size <= 0:
        raise HTTPException(400, "package_size must be > 0")
    if body.buy_amount is not None and body.buy_amount <= 0:
        raise HTTPException(400, "buy_amount must be > 0")
    if body.tracking_mode is not None and body.tracking_mode not in ("binary", "qty"):
        raise HTTPException(400, "tracking_mode must be 'binary' or 'qty'")
    new_barcode = repo._UNSET  # unset = leave the barcodes alone
    if body.barcode is not None:
        cleaned = re.sub(r"\D", "", body.barcode)
        if body.barcode.strip():
            if len(cleaned) != len(body.barcode.strip()) or not 6 <= len(cleaned) <= 14:
                raise HTTPException(400, "barcode must be 6-14 digits")
            clash = repo.find_item_by_barcode(cleaned)
            if clash and clash["id"] != item_id:
                raise HTTPException(409, f"barcode already used by {clash['name']}")
            new_barcode = cleaned
        else:
            new_barcode = None  # an empty barcode clears the mapping
    if body.category is not None and not body.category.strip():
        raise HTTPException(400, "category must not be empty")
    new_concept = repo._UNSET
    if body.concept_id is not None:
        cleaned = (body.concept_id or "").strip()
        if cleaned and cleaned not in catalog.CONCEPTS:
            raise HTTPException(400, f"unknown concept {cleaned}")
        new_concept = cleaned or None
    try:
        item = repo.update_item(item_id, body.min_quantity, body.package_size,
                                body.tracking_mode, buy_amount=body.buy_amount,
                                auto_restock=body.auto_restock,
                                barcode=new_barcode, name=body.name,
                                category=body.category, concept_id=new_concept,
                                generic_name=body.generic_name
                                if body.generic_name is not None else repo._UNSET)
    except ValueError as error:
        raise HTTPException(409, str(error))
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


@app.post("/api/items/{item_id}/snooze-low")
def snooze_low(item_id: str):
    """Dismiss the projected low prompt until the estimate drops below its
    level at dismissal (planning more meals re-raises it)."""
    item = repo.snooze_low(item_id)
    if not item:
        raise HTTPException(404, "item not found")
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


def _rematch_context() -> dict:
    """One stock snapshot for a read-time rematch: the live items, an
    exact-name map and a concept stock map — so a whole recipe list can
    re-resolve without a DB query per ingredient row."""
    items = repo.list_items()
    by_name: dict[str, dict] = {}
    for item in items:
        by_name.setdefault(item["name"].lower(), item)
    return {"items": items, "by_name": by_name, "stocked": catalog.stock_map(items)}


def _rematch_unconfirmed(recipe: dict, ctx: dict) -> dict:
    """Freshen unmatched ingredient rows IN MEMORY, no DB writes.

    Match state is written once at import (or by /api/catalog/standardize);
    stock moves on — a row that was resolved as "buy Hefe" keeps claiming
    Hefe is missing even after nine packs are scanned. The rematch re-runs
    the cascade for every tracked row *without* an item, so recipes follow
    the stock automatically. Sacred rows: confirmed items (item_id set,
    user intent) and untracked rows (water, prepared refs, junk).
    """
    for ing in recipe.get("ingredients") or []:
        if not ing.get("tracked") or ing.get("item_id"):
            continue
        raw = ing.get("raw") or ""
        parsed = extract.parse_ingredient_line(raw)
        name = (extract.base_ingredient_name((parsed or {}).get("name") or raw)
                or raw)
        # sizes stuck to the name ("2.5cm piece fresh ginger") resolve like
        # the plain food; the size only surfaces as a quantity on merge
        _, _, name = extract.split_size_prefix(name)
        fresh = _ingredient_entry(
            {"name": name, "raw": raw, "amount": ing.get("amount"),
             "unit": ing.get("unit")}, {}, ctx["items"], ctx)
        if fresh is None or fresh.get("tracked") is False:
            continue  # junk / prepared refs / staples: standardize owns them
        if fresh.get("item_id"):
            ing["item_id"] = fresh["item_id"]
            if fresh.get("concept_id"):
                ing["concept_id"] = fresh["concept_id"]
            ing["suggestion"] = None
            ing["substitute_kind"] = None
            ing["substitute_note"] = fresh.get("substitute_note") or None
        else:
            ing["concept_id"] = fresh.get("concept_id")
            ing["suggestion"] = fresh.get("suggestion")
            ing["substitute_kind"] = fresh.get("substitute_kind")
            ing["substitute_note"] = fresh.get("substitute_note")
    return recipe


@app.get("/api/recipes")
def get_recipes():
    # unmatched rows follow the live stock: state on disk is a snapshot
    # from import/standardize time and goes stale as items are added,
    # tagged, stocked or deleted
    ctx = _rematch_context()
    return camelize([_rematch_unconfirmed(r, ctx) for r in repo.list_recipes()])


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


def _ingredient_entry(ing: dict, canon: dict[str, str], items: list | None = None,
                     ctx: dict | None = None) -> dict | None:
    """One imported ingredient line -> its pantry row.

    Junk (equipment, page noise) is dropped by returning None; references
    to things the recipe itself prepares become untracked availability
    rows; everything else runs the concept cascade in app/catalog.py:

    identity -> auto-matched item, in stock variants/blends/siblings ->
    one-tap suggestion with kind + note, known-but-missing concept -> the
    German buy name, unknown -> the cleaned name (create-on-tap fallback).
    """
    name = extract.base_ingredient_name(ing["name"])
    name = (canon.get(name, name) or name).strip()
    if catalog.junk_class(name):
        return None
    # sizes stuck to the name ("2.5cm piece fresh ginger") are quantities:
    # resolve the plain food, the raw keeps its wording until a merge
    # lifts the size into the amount column
    _, _, name = extract.split_size_prefix(name)
    entry = {"raw": ing["raw"], "amount": ing.get("amount"), "unit": ing.get("unit"),
             "tracked": True, "suggestion": None}
    if ing.get("alt_group"):
        entry["alt_group"] = ing["alt_group"]
    if catalog.is_prepared_reference(ing.get("raw") or "", name) or name.lower() in ALWAYS_AVAILABLE:
        entry["tracked"] = False
        return entry
    items = items if items is not None else repo.list_items()
    # an exact item of the same name always wins (user-created names are
    # the strongest possible signal). CTX carries a precomputed exact-name
    # map and stock map so a read-time rematch needs no per-row DB query.
    item = (ctx["by_name"].get(name.lower()) if ctx
            else repo.find_item_by_name(name))
    if item:
        entry["item_id"] = item["id"]
        concept = catalog.resolve_item_concept(item)
        if concept:
            entry["concept_id"] = concept
        return entry
    res = catalog.resolve_for_stock(name, items,
                                   ctx["stocked"] if ctx else None)
    if res["concept"]:
        entry["concept_id"] = res["concept"]
    if res["kind"] == "staple":
        entry["tracked"] = False
        return entry
    if res["kind"] == "identity":
        entry["item_id"] = res["item_id"]
        if res["note"]:  # form-drift hint ("Samen statt gemahlen")
            entry["substitute_note"] = res["note"]
        return entry
    if res["kind"] in ("variant", "in_blend", "sibling"):
        entry["suggestion"] = res["item_name"]
        entry["substitute_kind"] = res["kind"]
        entry["substitute_note"] = res["note"]
        return entry
    if res["kind"] in ("components", "buy"):
        # the buy name doubles as the mapped item name when tapped:
        # confirming "Kreuzkümmel" once serves every future recipe
        entry["suggestion"] = res.get("buy_name") or name
        if res["kind"] == "components":
            entry["substitute_note"] = res["note"]
        return entry
    entry["suggestion"] = res["cleaned"] if res.get("cleaned") else name
    return entry


def _create_recipe_with_matches(data: dict, choice: dict | None = None, cloud: dict | None = None) -> dict:
    canon = _canonical_names(data, choice, cloud)
    items = repo.list_items()
    ingredients = [e for e in (_ingredient_entry(ing, canon, items) for ing in data["ingredients"]) if e]
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
    items = repo.list_items()
    ingredients = [e for e in (_ingredient_entry(ing, canon, items) for ing in data["ingredients"]) if e]
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
    recipe = _rematch_unconfirmed(recipe, _rematch_context())
    result = camelize(repo.cook_recipe(recipe, body.portions))
    _push_to_ha()
    return result


@app.post("/api/recipes/{recipe_id}/add-missing")
def add_missing(recipe_id: str, body: CookRequest):
    recipe = _get_recipe_or_404(recipe_id)
    recipe = _rematch_unconfirmed(recipe, _rematch_context())
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


def _missing_ingredient_groups() -> dict[str, dict]:
    """Ingredient rows the pantry cannot account for, grouped by the food
    they mean. Unmatched tracked rows only: confirmed rows are user intent,
    out-of-stock items are a shopping problem, not a matching one. Rows that
    DO stock-resolve at read time (fresh rematch) already carry an item and
    drop out. Grouping key: the shared catalog concept when the cascade
    knows the food ("Trockenhefe" and "instant yeast" are both yeast), the
    normalized cleaned name otherwise."""
    ctx = _rematch_context()
    groups: dict[str, dict] = {}
    for recipe in repo.list_recipes():
        recipe = _rematch_unconfirmed(recipe, ctx)
        for ing in recipe.get("ingredients") or []:
            if not ing.get("tracked") or ing.get("item_id"):
                continue
            raw = ing.get("raw") or ""
            parsed = extract.parse_ingredient_line(raw)
            name = (extract.base_ingredient_name((parsed or {}).get("name") or raw)
                    or raw).strip()
            # "2.5cm piece fresh ginger" groups and reads as "fresh ginger";
            # the size is a quantity and shows up on the rows instead
            _, _, name = extract.split_size_prefix(name)
            concept_id = ing.get("concept_id")
            key = f"concept:{concept_id}" if concept_id else f"name:{catalog._norm(name)}"
            g = groups.setdefault(key, {
                "key": key, "concept_id": concept_id, "name_counts": {},
                "recipes": {}, "row_count": 0, "sample_raw": raw, "rows": []})
            g["name_counts"][name] = g["name_counts"].get(name, 0) + 1
            g["row_count"] += 1
            g["recipes"][recipe["id"]] = recipe["title"]
            g["rows"].append({"recipe_id": recipe["id"], "ingredient_id": ing["id"],
                              "raw": raw, "amount": ing.get("amount"), "unit": ing.get("unit")})
    return groups


def _missing_groups_payload(groups: dict[str, dict]) -> list[dict]:
    out = []
    for g in groups.values():
        name = max(g["name_counts"].items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
        out.append({
            "key": g["key"],
            "name": name,
            "concept_id": g["concept_id"],
            "concept_label": (catalog.CONCEPTS.get(g["concept_id"]) or {}).get("de"),
            "recipe_count": len(g["recipes"]),
            "row_count": g["row_count"],
            "sample_raw": g["sample_raw"],
            "recipes": [{"id": rid, "title": title} for rid, title in g["recipes"].items()],
        })
    out.sort(key=lambda g: (-g["recipe_count"], g["name"].lower()))
    return out


def _merge_row_update(raw: str, target_name: str, amount, unit) -> tuple[str, object, str | None]:
    """One merged row's post-merge state: retexted onto the target food,
    keeping amounts and preparation notes, and with any size that was stuck
    to the name ("2.5cm piece fresh ginger") lifted out into the quantity
    so it multiplies with the portions setting."""
    parsed = extract.parse_ingredient_line(raw)
    base = ((extract.base_ingredient_name((parsed or {}).get("name") or raw) or raw)
            or "").strip()
    size_amount, size_unit, cleaned = extract.split_size_prefix(base)
    # size in the name and no parsed amount of its own: the size IS the
    # amount now ("2.5 cm fresh ginger, finely grated")
    if amount is None and size_amount is not None:
        suffix = ""
        if cleaned and cleaned.lower() in raw.lower():
            idx = raw.lower().index(cleaned.lower())
            suffix = raw[idx + len(cleaned):]
        return (f"{size_amount:g} {size_unit} {target_name}{suffix}".strip(),
                size_amount, size_unit)
    if base:
        idx = raw.lower().find(base.lower())
        if idx >= 0:
            return (raw[:idx] + target_name + raw[idx + len(base):]).strip(), amount, unit
    if amount is not None:
        return (f"{amount:g} {unit or ''} {target_name}".replace("  ", " ").strip(),
                amount, unit)
    return target_name, amount, unit


def _rows_for_missing_key(key: str) -> tuple[list[dict], str | None]:
    """The RECORDED rows of one missing-food key, straight from the database.

    The group list (GET) shows rows the live rematch still cannot account
    for. The merge cannot use that same recomputed snapshot: in the
    create-then-link flow the user has just created the item, so the
    rematch binds the group's rows to it in memory and the recomputed
    group comes back empty ("no unmatched recipe rows"). What a merge
    fixes is the recorded state; rows that already carry a confirmed
    item_id stay untouched.
    """
    rows: list[dict] = []
    recipes: dict[str, str] = {}
    concept = None
    for recipe in repo.list_recipes():
        for ing in recipe.get("ingredients") or []:
            if not ing.get("tracked") or ing.get("item_id"):
                continue
            raw = ing.get("raw") or ""
            parsed = extract.parse_ingredient_line(raw)
            name = (extract.base_ingredient_name((parsed or {}).get("name") or raw)
                    or raw).strip()
            _, _, name = extract.split_size_prefix(name)
            cid = ing.get("concept_id") or catalog.resolve(name)[0]
            row_key = f"concept:{cid}" if cid else f"name:{catalog._norm(name)}"
            if row_key != key:
                continue
            concept = concept or cid
            recipes[recipe["id"]] = recipe["title"]
            rows.append({"recipe_id": recipe["id"], "ingredient_id": ing["id"],
                         "raw": raw, "amount": ing.get("amount"), "unit": ing.get("unit")})
    return rows, concept, recipes


@app.get("/api/recipes/missing-items")
def missing_items():
    """Settings > Missing items: every unmatched recipe ingredient, grouped
    by food, sorted by how many recipes use it."""
    return camelize(_missing_groups_payload(_missing_ingredient_groups()))


@app.post("/api/recipes/missing-items/merge")
def merge_missing_item(body: MissingMergeRequest):
    """Merge one missing-food group into an inventory item: every recipe row
    is relinked AND rewritten to name the item ("250 g Trockenhefe" ->
    "250 g Hefe"). An untagged item inherits the group's concept so future
    imports of the same food stock-match immediately."""
    rows, group_concept, recipe_titles = _rows_for_missing_key(body.key)
    if not rows:
        raise HTTPException(404, "no unmatched recipe rows for this food")
    item = repo.get_item(body.item_id)
    if not item:
        raise HTTPException(404, "item not found")
    concept_id = item.get("concept_id")
    if not concept_id and group_concept:
        repo.set_item_concept(item["id"], group_concept)
        concept_id = group_concept
    target_name = (body.name or "").strip() or item["name"]
    updates = []
    for row in rows:
        raw, amount, unit = _merge_row_update(
            row["raw"], target_name, row["amount"], row["unit"])
        updates.append({
            "recipe_id": row["recipe_id"], "ingredient_id": row["ingredient_id"],
            "raw": raw, "amount": amount, "unit": unit,
            "item_id": item["id"], "concept_id": concept_id})
    repo.merge_ingredient_rows(updates)
    return camelize({
        "updated": len(updates),
        "item_name": item["name"],
        "recipes": [{"id": rid, "title": recipe_titles[rid]} for rid in recipe_titles],
    })


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
            if entry := _ingredient_entry(alt, {}):
                entries.append(entry)
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


@app.get("/api/catalog/search")
def catalog_search(q: str = ""):
    """Autocomplete suggestions for the tag picker: concepts whose label
    or alias contains the typed text, best matches first."""
    return camelize({"results": catalog.search_concepts(q)})


@app.get("/api/catalog/resolve")
def catalog_resolve(name: str):
    """Alias -> concept, for the item-detail tag picker. Unknown input
    resolves to {conceptId: null} instead of an error."""
    concept, cleaned = catalog.resolve(name)
    meta = catalog.CONCEPTS.get(concept)
    return {
        "conceptId": concept,
        "label": meta["de"] if meta else None,
        "family": meta["family"] if meta else None,
        "cleaned": cleaned,
    }


@app.post("/api/catalog/standardize")
def standardize_catalog():
    """One-shot catalog tidy-up. Deterministic only (no LLM):

    1. tag every inventory item with its food concept
    2. re-run the matching cascade over every recipe: confirmed matches are
       preserved, junk rows are dropped, prepared references become
       availability rows, suggestions/notes backfill the rest
    3. recipes whose rows changed get their (qty) step spans re-derived

    Idempotent; safe to re-run any time.
    """
    trace = telemetry.start_trace("catalog_standardize")
    telemetry.set_meta(note="deterministic rematch")
    summary = {"itemsTagged": 0, "itemsUnmatched": [], "matched": 0,
               "substitutions": 0, "buys": 0, "untracked": 0,
               "dropped": [], "recipesTouched": 0}
    for item in repo.list_items():
        concept = catalog.resolve_item_concept(item)
        # write unconditionally: stale tags from older runs clear too
        repo.set_item_concept(item["id"], concept)
        if concept:
            summary["itemsTagged"] += 1
        else:
            summary["itemsUnmatched"].append(item["name"])
    items = repo.list_items()  # refreshed, now carrying concept ids
    for recipe in repo.list_recipes():
        touched = False
        for ing in recipe["ingredients"]:
            if ing.get("item_id") and ing.get("tracked"):
                continue  # confirmed matches are sacred
            raw = ing.get("raw") or ""
            parsed = extract.parse_ingredient_line(raw)
            name = extract.base_ingredient_name((parsed or {}).get("name") or raw) or raw
            fresh = _ingredient_entry(
                {"name": name, "raw": raw, "amount": ing.get("amount"),
                 "unit": ing.get("unit")}, {}, items)
            if fresh is None:  # equipment / page noise
                repo.delete_ingredient(recipe["id"], ing["id"])
                summary["dropped"].append({"recipe": recipe["title"], "raw": raw[:80]})
                touched = True
                continue
            if ing.get("tracked") and fresh.get("tracked") is False:
                repo.standardize_ingredient(recipe["id"], ing["id"], {"tracked": False})
                summary["untracked"] += 1
                touched = True
                continue
            if fresh.get("item_id") and not ing.get("item_id"):
                repo.standardize_ingredient(recipe["id"], ing["id"], {
                    "item_id": fresh["item_id"],
                    "concept_id": fresh.get("concept_id"),
                    "suggestion": None,
                    "substitute_kind": None,
                    "substitute_note": fresh.get("substitute_note"),
                })
                summary["matched"] += 1
                touched = True
                continue
            fields = {"suggestion": fresh.get("suggestion"),
                       "concept_id": fresh.get("concept_id"),
                       "substitute_kind": fresh.get("substitute_kind"),
                       "substitute_note": fresh.get("substitute_note")}
            if any(ing.get(k) != v for k, v in fields.items()):
                repo.standardize_ingredient(recipe["id"], ing["id"], fields)
                if fields.get("suggestion"):
                    kind = fresh.get("substitute_kind")
                    if kind in ("variant", "in_blend", "sibling"):
                        summary["substitutions"] += 1
                    elif kind is None and fresh.get("concept_id"):
                        summary["buys"] += 1
                touched = True
        if touched:
            summary["recipesTouched"] += 1
            updated = repo.get_recipe(recipe["id"])
            # deterministic relink only: provider "disabled" makes every
            # LLM call short-circuit; word-boundary spans still apply
            links = extract.link_ingredients_in_steps(updated["steps"],
                                                      updated["ingredients"],
                                                      {"provider": "disabled",
                                                       "model": "none"}, None)
            repo.set_step_ingredient_links(recipe["id"], links)
    telemetry.set_meta(**summary)
    trace.finish("ok")
    return summary  # already camelCase


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


def _png_response(image) -> Response:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


def _lan_ip() -> str | None:
    """The host's outbound LAN IPv4, without sending a packet (the UDP
    "connect" only makes the routing decision). None when there is no
    route. Note for Docker deployments: this is the *container's* address
    (172.x) — set `label_base_url` explicitly there."""
    for target in (("8.8.8.8", 80), ("1.1.1.1", 53)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(target)
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            continue
        finally:
            sock.close()
    return None


def _label_base_url(request: Request) -> str:
    """Origin the label QRs point at (phones must be able to open it):
    1. the `label_base_url` setting when filled in Settings,
    2. else the server's own LAN IP on this request's port (auto-detect),
    3. else whatever origin the request arrived on.
    """
    configured = (repo.get_setting("label_base_url") or "").strip()
    if configured:
        return configured.rstrip("/")
    ip = _lan_ip()
    if ip:
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        scheme = "https" if port == 443 else "http"
        return f"{scheme}://{ip}:{port}"
    return str(request.base_url).rstrip("/")


class LabelDesignRequest(BaseModel):
    """Editor save: the element list (mm boxes), label width and tape. A
    missing element list starts from the tape's default preset (fresh
    'Create custom label' checkbox)."""
    elements: list[dict] | None = None
    widthMm: float = 50
    tape: int = 24


def _validated_tape(tape: int) -> int:
    return tape if tape in labels.TAPE_GEOMETRY else 24


def _num(value, default: float, low: float | None = None,
         high: float | None = None) -> float:
    """Coerce an element field to a sane number — the editor sends trusted
    data, but a stale bookmark or manual API call must not 500 the save."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if low is not None:
        number = max(low, number)
    if high is not None:
        number = min(high, number)
    return number


def _validated_design(body: LabelDesignRequest) -> tuple[list[dict], float, int]:
    elements = body.elements if body.elements is not None else labels.default_elements(body.tape)
    if len(elements) > 60:
        raise HTTPException(400, "too many label elements")
    clean = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        font_pt = _num(el.get("fontSizePt"), 10, 0, 300)
        clean.append({
            "id": str(el.get("id") or f"el{len(clean)}"),
            "field": str(el.get("field") or "text").lower(),
            "x": _num(el.get("x"), 0, -50, 300), "y": _num(el.get("y"), 0, -50, 100),
            "w": _num(el.get("w"), 10, 0.1, 300), "h": _num(el.get("h"), 5, 0.1, 100),
            "fontSizePt": font_pt,
            "text": str(el.get("text") or "")[:200],
        })
    return clean, max(10.0, min(300.0, _num(body.widthMm, 50))), _validated_tape(body.tape)


@app.get("/api/labels/control-codes")
def get_control_codes():
    """The scanner control-code set for the frontend (single source of truth:
    labels.py feeds the bridge, the print page, the stickers and this API)."""
    return camelize([
        {"key": key, "code": meta["code"], "label": meta["label"],
         "hint": meta["hint"]}
        for key, meta in labels.CONTROL_CODES.items()
    ])


# ------------------------------------------------- per-item custom label designs

@app.get("/api/labels/custom")
def list_custom_labels():
    """All items with a custom label, most recently added first."""
    return camelize(repo.list_item_custom_labels())


@app.get("/api/labels/custom/item/{item_id}")
def get_item_custom_label(item_id: str):
    design = repo.get_item_custom_label(item_id)
    if not design:
        raise HTTPException(404, "no custom label for this item")
    return camelize(design)


@app.put("/api/labels/custom/item/{item_id}")
def put_item_custom_label(item_id: str, body: LabelDesignRequest):
    item = repo.get_item(item_id)
    if not item:
        raise HTTPException(404, "item not found")
    elements, width_mm, tape = _validated_design(body)
    design = repo.save_item_custom_label(item_id, elements, width_mm, tape)
    return camelize(design)


@app.delete("/api/labels/custom/item/{item_id}")
def delete_item_custom_label(item_id: str):
    deleted = repo.delete_item_custom_label(item_id)
    if not deleted:
        raise HTTPException(404, "no custom label for this item")
    return {"deleted": True}


@app.get("/api/labels/custom/item/{item_id}/png")
def item_custom_label_png(item_id: str, request: Request):
    """Rendered PNG of the saved design (list thumbnails, single prints)."""
    item = repo.get_item(item_id)
    design = repo.get_item_custom_label(item_id)
    if not item or not design:
        raise HTTPException(404, "no custom label for this item")
    image = labels.render_custom_label(
        design["elements"], labels.item_label_data(item, _label_base_url(request)),
        design["width_mm"], design.get("tape", 24))
    return _png_response(image)


@app.post("/api/labels/preview/item/{item_id}")
def item_custom_label_preview(item_id: str, body: LabelDesignRequest, request: Request):
    """Unsaved-work preview for the editor: render the work-in-progress
    layout against the item's real data without persisting anything."""
    item = repo.get_item(item_id)
    if not item:
        raise HTTPException(404, "item not found")
    elements, width_mm, tape = _validated_design(body)
    image = labels.render_custom_label(
        elements, labels.item_label_data(item, _label_base_url(request)),
        width_mm, tape)
    return _png_response(image)


@app.get("/api/labels/custom.lemd")
def custom_labels_lemd(request: Request, ids: str, tape: int = 24):
    """Epson Label Editor mobile strip over the *saved* designs of the
    given items ('ids' comma-separated), separated by dashed cut marks —
    the batch print of the Barcodes page."""
    tape = _validated_tape(tape)
    images = []
    for item_id in [part.strip() for part in ids.split(",") if part.strip()]:
        item = repo.get_item(item_id)
        design = repo.get_item_custom_label(item_id)
        if not item or not design:
            raise HTTPException(404, f"no custom label for item: {item_id}")
        images.append(labels.render_custom_label(
            design["elements"], labels.item_label_data(item, _label_base_url(request)),
            design["width_mm"], design.get("tape", 24)))
    if not images:
        raise HTTPException(400, "no item ids given")
    return _lemd_response(labels.generate_lemd(images, tape), "openpantry-custom-labels.lemd")


# ---------------------------------------------- control-code sticker designs

def _control_or_404(control: str) -> str:
    if control not in labels.CONTROL_CODES:
        raise HTTPException(404, "unknown control code")
    return control


def _control_design(control: str) -> dict:
    """Saved sticker design, or LabelGenerator's default caption + code
    graphic when the user hasn't customized it yet."""
    design = repo.get_control_custom_label(control)
    if design:
        return design
    return {"elements": [dict(el) for el in labels.DEFAULT_CONTROL_LAYOUT],
            "width_mm": 50, "tape": 24, "control": control}


@app.get("/api/labels/custom/control/{control}")
def get_control_custom_label(control: str):
    control = _control_or_404(control)
    return camelize(_control_design(control))


@app.put("/api/labels/custom/control/{control}")
def put_control_custom_label(control: str, body: LabelDesignRequest):
    control = _control_or_404(control)
    elements, width_mm, tape = _validated_design(body)
    design = repo.save_control_custom_label(control, elements, width_mm, tape)
    return camelize(design)


@app.post("/api/labels/preview/control/{control}")
def control_custom_label_preview(control: str, body: LabelDesignRequest):
    control = _control_or_404(control)
    elements, width_mm, tape = _validated_design(body)
    image = labels.render_custom_label(
        elements, labels.control_label_data(control), width_mm, tape)
    return _png_response(image)


@app.get("/api/labels/custom/control/{control}/png")
def control_custom_label_png(control: str):
    control = _control_or_404(control)
    design = _control_design(control)
    image = labels.render_custom_label(
        design["elements"], labels.control_label_data(control),
        design["width_mm"], design.get("tape", 24))
    return _png_response(image)


@app.get("/api/labels/control-codes.lemd")
def control_codes_lemd(request: Request, tape: int = 24, format: str = "ean"):
    """Epson strip with the two scanner control-code stickers (their saved
    custom designs when present); format=qr swaps EAN graphics for QR codes
    of the same digits (2D-only scanners)."""
    tape = _validated_tape(tape)
    images = []
    for control in labels.CONTROL_CODES:
        design = _control_design(control)
        images.append(labels.render_custom_label(
            design["elements"], labels.control_label_data(control),
            design["width_mm"], design.get("tape", 24),
            qr_instead_of_ean=format == "qr"))
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
    consumed = repo.consume_item(item["id"], item["package_size"])
    _record_scan_event("consume", None, consumed or item)  # live UI refresh ping
    _push_to_ha()
    return camelize(consumed or item)


@app.get("/api/scan/recent")
def scan_recent(limit: int = 60):
    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit must be 1-500")
    return {"scans": camelize(repo.recent_scans(limit))}


def _lemd_response(payload: str, filename: str) -> Response:
    return Response(
        content=payload,
        # NOT application/json: browsers append ".json" to the filename when
        # the MIME type doesn't match the extension, and the Epson Label
        # Editor app then fails to recognise the file as a .lemd strip
        media_type="application/octet-stream",
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
