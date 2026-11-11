# OpenPantry

Self-hosted home food and consumables inventory. Runs on a Rock 5A (16 GB) on the LAN.

## How it works

- **Receipts in:** forward grocery receipt mails to a polled IMAP mailbox. OCR (Tesseract) + a local LLM (Ollama) extract line items; they land in a review queue.
- **Generic product catalog:** barcodes and receipt lines map to generic items ("Bad Reichenhaller Jodarmes Salz" → *Salz*), with LLM/fuzzy suggestions confirmed once by the user.
- **Stock out:** scan the product barcode or open the NFC/QR tag URL (`/c/<item>`) on your phone to record consumption.
- **Recipes:** paste a link or recipe text; a standardized format stores ingredients per base portions. The list highlights recipes that can be made with current stock (orange) vs. greyed-out ones showing how many portions are possible; missing ingredients can be added to the shopping list, scaled by the selected portions and rounded up to package sizes.
- **Cooking:** "Cooked this" deducts used ingredients; items that fall low afterwards appear on Home as "might be running low" (a weak signal the user confirms with Yes/No, overridden by any barcode scan).
- **Shopping list:** merged per product, package-size aware; later pushed to Home Assistant.
- **Model settings:** the receipts and recipes areas each let you pick which model runs the extraction — any installed Ollama model, or a cloud model via an OpenAI-compatible API (base URL, model, API key; defaults to Mistral's API). The key is stored server-side and never returned by the API.

The LLM only proposes; deterministic code validates and commits. The SQLite database is the single source of truth.

## Layout

```
frontend/   Mobile-first PWA (React + Vite + TypeScript)
backend/    FastAPI + SQLite: REST API, recipe import (schema.org → LLM → heuristic fallback),
            receipt OCR/extraction, IMAP polling worker, NFC/QR consume landing pages
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
