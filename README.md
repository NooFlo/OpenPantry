# OpenPantry

Self-hosted home food and consumables inventory. Runs on a Rock 5A (16 GB) on the LAN.

## How it works

- **Receipts in:** forward grocery receipt mails to a polled IMAP mailbox. OCR (Tesseract) + a local LLM (Ollama) extract line items.
- **Generic product catalog:** barcodes map to generic items ("Bad Reichenhaller Jodarmes Salz" → *Salz*), resolved via Open Food Facts and LLM suggestions, confirmed once by the user.
- **Stock out:** scan the product barcode or an NFC/QR tag on a permanent container with your phone to record consumption.
- **Shopping list:** deterministic low-stock/run-out prediction, formatted by the local LLM and pushed to Home Assistant.
- **Recipes:** paste a link or recipe text; a standardized format stores ingredients per base portions. The list highlights recipes that can be made with current stock (orange) vs. greyed-out ones showing how many portions are possible; missing ingredients can be added to the shopping list, scaled by the selected portions and rounded up to package sizes.
- **Cooking:** "Cooked this" deducts used ingredients; items that fall low afterwards appear on Home as "might be running low" (a weak signal the user confirms with Yes/No, overridden by any barcode scan).

The LLM only proposes; a deterministic pipeline validates and commits. The inventory database stays the single source of truth.

## Layout

```
frontend/   Mobile-first PWA (React + Vite + TypeScript), currently on mock data
```

Planned: `ingest/` (IMAP → OCR → LLM worker), `bridge/` (scan/NFC/QR consume endpoint), `docker-compose.yml` (Grocy, Ollama, workers).

## Frontend development

```bash
cd frontend
npm install
npm run dev      # dev server, LAN-reachable
npm run build    # typecheck + production build
```

The UI has three tabs (Home, Inventory, Recipes); receipts are a submenu inside Inventory. Dark/light theme follows the system preference with a manual toggle. All data flows through `src/api.ts`, which is the seam where the backend will be wired in.
