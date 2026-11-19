# OpenPantry

Self-hosted home food and consumables inventory. Runs on a Rock 5A (16 GB) on the LAN.

## How it works

- **Receipts in:** forward grocery receipt mails to a polled IMAP mailbox. OCR (Tesseract) + a local LLM (Ollama) extract line items; they land in a review queue.
- **Generic product catalog:** barcodes and receipt lines map to generic items ("Bad Reichenhaller Jodarmes Salz" → *Salz*), with LLM/fuzzy suggestions confirmed once by the user.
- **Barcode product lookups (backend):** scanning an unknown barcode queries Open Food Facts (plus Open Beauty/Open Products Facts for cosmetics and household goods), caches the product in SQLite and proposes generic-catalog mappings — `POST /api/barcode/lookup`, the `GET /api/barcode/pending` review queue and `POST /api/barcode/assign` to confirm a mapping. Germany's store brands dominate usage, so name/category matching runs on containment and token heuristics, and every lookup is fetched at most once (negative results re-check after two weeks).
- **Barcode scan modes (control-code stickers):** a USB scanner bridge (keyboard-wedge scanners) runs on the Rock5; scanning one of the printed control codes from `GET /print/control-codes` — BOUGHT, EMPTY/TRASH, CONSUME in the GS1 in-store EAN range — switches what subsequent product scans do: restock a package, zero the item and re-order it, or the default package consumption. The mode is sticky until the next control code and logged per scan; unknown barcodes land in the Open Food Facts review queue regardless of mode.
- **Multiple barcodes per item:** one generic inventory item backs many product barcodes — Aldi/REWE/Edeka egg cartons all deduct from the same "Eier" stock. Item settings list the attached barcodes with per-code removal and an add field (`POST/DELETE /api/items/{id}/barcodes`); a barcode can only ever point at one item (409 on clashes).
- **Labels & Epson export:** the Inventory screen has a "Labels & barcodes" settings submenu (barcode icon): a per-item barcode field (the USB scanner's mapping, editable) plus label printing. Item labels pair a QR to the item's consume page with the name and (24 mm tape) the product barcode, rendered like LabelGenerator and exported as `.lemd` strips for the Epson Label Editor mobile app — items are picked individually (the point is working with the barcodes printed on the products, so labels are opt-in), alongside the three control codes, on 12/24 mm tape with dashed cut marks. `GET /api/labels/item/{id}/png` previews a label.
- **Stock out:** scan the product barcode or open the NFC/QR tag URL (`/c/<item>`) on your phone to record consumption. Each item can also expose a copyable NFC link for tags, QR stickers and the Shortcuts app.
- **Tracking modes:** each item is either binary (in stock / not in stock) or quantity-tracked (a rounded stock count, no gram-level values in the UI). Enter several packages of one product from a receipt and it switches to quantity tracking automatically; switch it manually in the item's settings sheet. Exact per-recipe amounts (g, ml, …) are still stored in the background for deductions and the low-stock prognosis.
- **Low-stock alarms:** every item carries an alarm threshold (minimum quantity / "when empty"). Below it, the item surfaces on Home as a "might be running low" card to confirm Yes/No and lands on the shopping list. Thresholds are adjusted with steppers in the item's settings sheet.
- **Recipes:** paste a link or recipe text; a standardized format stores ingredients per base portions. Search, category filter chips and newest/quickest/A–Z sorts; recipes imported from a link can be refreshed to re-pull tags, times and the photo; wide screens show the list and the detail side by side. The list highlights recipes that can be made with current stock (orange) vs. greyed-out ones showing how many portions are possible; missing ingredients can be added to the shopping list, scaled by the selected portions and rounded up to package sizes.
- **Per-ingredient stock check:** the recipe detail walks every ingredient against current stock — in-stock ingredients show orange with a checked box, missing ones are greyed out, and unmapped ingredients offer one-tap suggestions to map them to inventory items. Staples that every kitchen has (water) are never stock-tracked and always count as available.
- **Alternative ingredients ("and/or"):** ingredient lines like "Basmati rice and/or naan to serve" are split at import into their options, shown as one pick-one card. The picked option is what goes on the shopping list when it's missing (an unpicked group waits until one is chosen) and the one "Cooked this" deducts; a group counts as in stock as soon as any option is available.
- **Recipe editing:** an "Edit" button (top right of the recipe detail) opens the recipe as plain text — title, source, base portions, every ingredient line and every step — with add/remove buttons for ingredients and steps. Lines whose text didn't change keep their pantry matches; changed lines are re-parsed and re-matched like an import (including and/or splitting). Editing also offers deleting the recipe.
- **Live step quantities:** at import, quantified ingredient mentions in the step texts are recorded as character spans (LLM proposes paraphrases like "the marinade"; deterministic word-boundary matching validates and places them — an ingredient's name can never be stolen by a wrong alias). The recipe UI renders a live "(qty)" in accent color behind every mention, scaled by the portions stepper and shown in household units (0.25 kg → 250 g; 2 portions of a 120 g/4-portion recipe → `60 g`). Ingredient rows display in the same smart units; the spans re-derive whenever steps or ingredient lines are edited.
- **Cooking:** "Cooked this" deducts used ingredients; items that fall low afterwards appear on Home as "might be running low" (a weak signal the user confirms with Yes/No, overridden by any barcode scan).
- **Shopping list:** merged per product, package-size aware; any change is pushed to a Home Assistant to-do list (`HA_URL`, `HA_TOKEN`, `HA_ENTITY`), configured from the Home screen's shopping-list sheet.
- **Model settings:** the receipts and recipes areas each let you pick which model runs the extraction — any installed Ollama model, or a cloud model via an OpenAI-compatible API (base URL, model, API key; defaults to Mistral's API). The key is stored server-side and never returned by the API.
- **Responsive layout:** mobile-first PWA with a bottom tab bar; from ~1180 px the app switches to a sidebar navigation with master-detail panes (recipe list + detail, inventory list + item detail).

The LLM only proposes; deterministic code validates and commits. The SQLite database is the single source of truth.

## Layout

```
frontend/   Mobile-first PWA (React + Vite + TypeScript)
backend/    FastAPI + SQLite: REST API, recipe import (schema.org → LLM → heuristic fallback),
            receipt OCR/extraction, IMAP polling worker, NFC/QR consume landing pages,
            Home Assistant shopping-list push, per-stage ingestion timing traces
tests       backend/tests (pytest), frontend typecheck via build
```

## Running

```bash
cp .env.example .env      # optional: IMAP credentials, Ollama model
docker compose up --build -d
# UI on http://<rock5a>:8321, pull the LLM once: docker compose exec ollama ollama pull qwen2.5:3b-instruct
```

Without Docker:

```bash
cd frontend && npm install && npm run build
cd ../backend && pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8321   # serves the API and the built frontend
```

The database is seeded with demo data on first start. Ollama and IMAP are optional: without them, recipe import falls back to a deterministic parser and receipts wait unprocessed.

## Development

```bash
cd frontend && npm run dev        # dev server with /api proxied to :8321
cd backend && python -m pytest tests/ -q
```

All frontend data flows through `src/api.ts`, which maps 1:1 to the backend's `/api` endpoints.
