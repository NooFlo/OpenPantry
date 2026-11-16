# Receipt pipeline notes — small models on the Rock 5

Run date: REWE eBon (`Inspiration/REWE-ebon.pdf`) pushed through the real pipeline
code (`app/extract.py` / `app/llm.py`) against locally installed
`qwen2.5:0.5b-instruct` and `qwen2.5:3b-instruct` (the production default).
Ground truth: 9 items (2 sold by weight), total 20.03 EUR, date 2026-11-11.

## What the run showed

### Stage 1: PDF never reaches the LLM (pipeline dead-end)
`mail.ATTACHMENT_RE` accepts `.pdf`, but Tesseract cannot read PDFs
(`pixReadStream: Pdf reading is not supported`), and the Dockerfile installs no
poppler/pdfium. An eBon PDF attachment therefore lands as an **empty receipt**
with the store guessed from the mail subject — the LLM never runs.

Fix options, cheapest first:
1. Try a text-layer extraction first (`pdftotext` / `pypdfium2`); most eBons
   (REWE, dm, many drugstores) are digitally generated and extract perfectly —
   OCR becomes the fallback for photo receipts.
2. If rasterizing, `pdftoppm -r 300` produced near-perfect OCR (deu+eng, 1.37 s
   on an M-series Mac; budget roughly 5-10x that on the Rock 5).

### Stage 2: LLM extraction — measured accuracy
With the current prompt (via the real `llm_receipt_items` code path):

| model | items found | quantity correct | total | verdict |
|---|---|---|---|---|
| qwen2.5:0.5b | 0/9 (invents store-address "products") | 0/9 | 38.4 (hallucinated) | unusable |
| qwen2.5:3b    | 5/9, first four items dropped | 0/9 (prices copied into quantity) | 18.72 (Netto, not paid total) | not trustworthy |

An improved prompt (explicit product-line grammar, weight-line rule, field
definitions) raised 0.5b recall to ~8/9 names but quantities stayed garbage;
3b went *down* (3/9 at temp 0). Sampling instability: `_generate_json_local`
sends no `options`, so Ollama defaults to temperature 0.8 — two identical runs
gave 8/6/... items. **Setting `temperature: 0` made runs byte-identical** —
cheap determinism win, though not an accuracy win.

Small models reliably extract `store` and `date` (TSE-Start's ISO timestamp
helps), but cannot do the column-to-field mapping (name | price | qty columns;
weight lines attached to the *previous* product). Extra schema fields made it
worse, not better.

### Stage 3: deterministic parsing wins the structure
A ~25-line regex parser over the same OCR text: **9/9 items, exact weights
(0.340 kg / 0.318 kg), exact total, date and store.** German receipts have a
strict grammar (`NAME PRICE B`, `W kg x P EUR/kg`, `SUMME EUR T`) — the LLM is
the wrong tool for this. Situations without a clean grammar (crumpled photos,
unusual stores) can still fall back to the LLM path.

### Stage 4: mapping to generic catalog items
`best_name_match` (whole-line SequenceMatcher) scored **0/9** on real REWE raw
names — margin over 0.75 is never reached; receipts get no suggestions at all.

- A cheap token-prefix/substring heuristic classified the easy subset with zero
  false positives: BANANE CHIQUITA → Bananen, MEERSALZ GROB → Salz.
- 3b as a constrained classifier (catalog list in prompt, temp 0): Bananen and
  Salz correct, one classic false positive (APFEL TENROY → Apfelsaft), Pecorino/
  Grana → Parmesan left as null — good **suggestion generator** if nulls go to
  the review queue. 0.5b degenerated and is not usable for this either.
- Semantic matches like Pecorino/Grana → Parmesan are best served by a learned
  alias table: every user confirmation (raw fragment → item) should be stored
  and checked before the LLM, ideally matching on generic tokens
  ("pecorino romano" → "pecorino") since brands rarely repeat.

## Recommended pipeline (small-model friendly)

```
attachment → text-layer extract (PDF) else tesseract 300dpi
           → regex receipt parser (products, weights, total, date)
           → per item: alias table → token heuristic → LLM classify (3b, temp 0)
           → review queue (user confirms once; confirmation trains the alias table)
```

Concrete code changes, ordered by impact per effort:

1. **Fix PDF ingestion** (text layer first, OCR fallback) — currently eBons
   silently become empty receipts.
2. **Deterministic receipt parser before `llm_receipt_items`**; keep the LLM
   path only as fallback when the parser finds no product lines. Add a checksum:
   parsed item prices must sum to SUMME±0.01; mismatch → flag for review.
3. **Pin `options: {"temperature": 0}`** (and `num_ctx` explicitly) in
   `_generate_json_local`; Ollama defaults to 0.8.
4. **Ask the LLM only for classification** (rawName → catalog item or null,
   catalog in prompt, one call per receipt), not numeric extraction. Run items
   the alias table + heuristic already matched without any LLM call at all.
5. **Robust parsing of model output**: `float(data.get("total") or 0)` raises
   an uncaught ValueError on German-format strings like `"20,03"` — a plausible
   small-model output — which kills the whole receipt. Normalize with a helper
   (strip currency, comma→dot) and validate `date` against YYYY-MM-DD before
   storing it (bad dates break `ORDER BY date` string sort).
6. **Add qty/unit/price to the receipt schema** so weight produce is trackable
   (0.5 kg Bananen, not "1 package"), as the recipe side already does.
7. **Learn from confirmations**: persist raw→item mappings from the review
   queue so each product only needs the user once — this is what makes the
   whole thing practical regardless of model size.

## Cost picture on the Rock 5A

3b extraction of this 450-token prompt took ~3.4 s eval on an M-series Mac;
expect roughly 10-20 s on the Rock 5A per receipt plus model load time if RAM
pressured. With the recommended split (deterministic parse + one small
classification call) the LLM sees only ~1-2k tokens and produces ~100, a few
seconds even for a slow SoC; receipts where everything matches the alias table
cost zero LLM time.
