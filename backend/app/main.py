import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import extract, mail, repo, seed
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


class BarcodeRequest(BaseModel):
    barcode: str


class ConfirmLowRequest(BaseModel):
    is_low: bool


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


@app.get("/api/items")
def get_items():
    return camelize(repo.list_items())


@app.post("/api/items/{item_id}/consume")
def consume(item_id: str, body: ConsumeRequest):
    item = repo.consume_item(item_id, body.amount)
    if not item:
        raise HTTPException(404, "item not found")
    return camelize(item)


@app.post("/api/scan/barcode")
def scan_barcode(body: BarcodeRequest):
    item = repo.find_item_by_barcode(body.barcode)
    if not item:
        raise HTTPException(404, "unknown barcode")
    return camelize(repo.consume_item(item["id"], item["package_size"]))


@app.post("/api/items/{item_id}/confirm-low")
def confirm_low(item_id: str, body: ConfirmLowRequest):
    item = repo.confirm_low(item_id, body.is_low)
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
    return camelize(repo.match_receipt_item(receipt_id, item_id, item["name"]))


@app.get("/api/recipes")
def get_recipes():
    return camelize(repo.list_recipes())


@app.post("/api/recipes/import")
def import_recipe(body: ImportRequest):
    try:
        if body.kind == "link":
            data = extract.import_recipe_from_url(body.value)
        elif body.kind == "text":
            data = extract.import_recipe_from_text(body.value)
        else:
            raise HTTPException(400, "kind must be 'link' or 'text'")
    except httpx.HTTPError:
        raise HTTPException(502, "could not fetch the recipe URL")
    if not data["ingredients"]:
        raise HTTPException(422, "could not extract any ingredients")
    return camelize(_create_recipe_with_matches(data))


def _create_recipe_with_matches(data: dict) -> dict:
    ingredients = []
    for ing in data["ingredients"]:
        entry = {"raw": ing["raw"], "amount": ing.get("amount"), "tracked": True, "suggestion": None}
        if ing.get("unit") and ing.get("amount") is not None:
            item = repo.find_item_by_name(ing["name"])
            if item:
                entry["item_id"] = item["id"]
            else:
                match = repo.best_name_match(ing["name"])
                entry["suggestion"] = match["name"] if match else ing["name"]
        else:
            entry["tracked"] = False
        ingredients.append(entry)
    return repo.create_recipe(data["title"], data["source"], data["base_portions"], ingredients, data["steps"])


def _get_recipe_or_404(recipe_id: str) -> dict:
    recipe = repo.get_recipe(recipe_id)
    if not recipe:
        raise HTTPException(404, "recipe not found")
    return recipe


@app.post("/api/recipes/{recipe_id}/cook")
def cook(recipe_id: str, body: CookRequest):
    recipe = _get_recipe_or_404(recipe_id)
    return camelize(repo.cook_recipe(recipe, body.portions))


@app.post("/api/recipes/{recipe_id}/add-missing")
def add_missing(recipe_id: str, body: CookRequest):
    recipe = _get_recipe_or_404(recipe_id)
    items_by_id = {i["id"]: i for i in repo.list_items()}
    return camelize(repo.add_missing_to_shopping_list(recipe, items_by_id, body.portions))


@app.post("/api/recipes/{recipe_id}/ingredients/{ingredient_id}/match")
def match_ingredient(recipe_id: str, ingredient_id: str, body: IngredientMatchRequest):
    recipe = _get_recipe_or_404(recipe_id)
    ingredient = next((i for i in recipe["ingredients"] if i["id"] == ingredient_id), None)
    if not ingredient:
        raise HTTPException(404, "ingredient not found")
    item = repo.find_item_by_name(body.item_name)
    if not item:
        item = repo.create_item(name=body.item_name)
    amount = ingredient["amount"]
    if amount is None:
        numbers = re.findall(r"\d+(?:[.,]\d+)?", ingredient["raw"])
        amount = float(numbers[0].replace(",", ".")) if numbers else 1.0
    return camelize(repo.match_recipe_ingredient(recipe_id, ingredient_id, item["id"], amount))


@app.post("/api/recipes/{recipe_id}/ingredients/{ingredient_id}/untrack")
def untrack_ingredient(recipe_id: str, ingredient_id: str):
    _get_recipe_or_404(recipe_id)
    return camelize(repo.untrack_recipe_ingredient(recipe_id, ingredient_id))


@app.get("/api/shopping-list")
def get_shopping_list():
    return camelize(repo.list_shopping_list())


@app.post("/api/shopping-list/{item_id}")
def add_to_list(item_id: str, body: ShoppingListRequest):
    try:
        return camelize(repo.add_to_shopping_list(item_id, body.amount))
    except KeyError:
        raise HTTPException(404, "item not found")


@app.delete("/api/shopping-list/{item_id}")
def remove_from_list(item_id: str):
    return camelize(repo.remove_from_shopping_list(item_id))


@app.get("/c/{item_id}", response_class=HTMLResponse)
def consume_landing(item_id: str):
    item = repo.get_item(item_id)
    if not item:
        raise HTTPException(404, "item not found")
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
<p>{item["quantity"]} {item["unit"]} in stock</p>
<button onclick="consume()">Used up one package ({item["package_size"]} {item["unit"]})</button>
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


@app.get("/api/health")
def health():
    return {"ok": True, "llm": extract.llm.available(), "mail": mail.enabled()}


if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def index():
        return "<html><body><p>OpenPantry backend running. Build the frontend or see /docs.</p></body></html>"
