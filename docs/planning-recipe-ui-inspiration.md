# Recipe UI inspiration analysis (planned work)

Status: planning only. Source images: `Inspiration/1.png`, `Inspiration/2.png`
(chef-centric dark recipe app; CREME-style grocery checklist app).

## Canonical element mapping

1. **Recipe images** — Andy-cooks JSON-LD exposes `image`; importer currently
   drops it. Phase 1 addition: `image_url` column + extraction. Cards without an
   image (pasted text) fall back to tinted surface block.
2. **Recipe list cards** — full-bleed photo, frosted overlay strip bottom with
   title; time chip; cookable badge (existing logic) top-right. Image 1 left
   screen.
3. **Detail as hero** — photo behind, rounded content `Sheet` floating over it
   (bigger radius, negative margin; CSS only).
4. **Meta chips** — total-time chip ("25m") from planned `total_minutes`;
   "Ready HH:MM" = now + total time, computed client-side (standout idea).
5. **Action hierarchy** — one filled primary pill ("Add missing" / "Cooked
   this"), rest ghost; portions stepper condensed into a compact chip in the
   action row. Skip: preview, play music.
6. **Search above filters** — rounded search field narrows by title/tag text;
   chip bar (planned tag filters) narrows by tag. Both combine.
7. **Ingredient toggles (Image 2 "Grocery")** — highest-value element: per-
   ingredient toggle pre-set from actual stock, replacing passive
   "missing x / in stock" text. Mirrors Andy-cooks "tick what's in your
   kitchen". Shopping list action uses only ticked ingredients (fixes stale
   stock entries). Amount shown under name, scaled to portions. Orange toggle
   matches existing `--accent`.
8. **Floating pill tab bar** — `TabBar.tsx` restyle into floating rounded pill;
   background already translucent via `color-mix` (styles.css:122). ~15 lines
   CSS + new `--glass` token. Active orange already fits.
9. **Group-title counts** — "Your recipes · 5" match count next to section
   titles / filtered list.
10. **Skipped** — creator profiles/avatars, ratings, paywall "Free" badges,
    notification bell, share, feed pagination.

## Plan deltas (relative to the tag/filter plan)

- Phase 1: add `image_url` to recipes + JSON-LD `image` extraction.
- Phase 4: search field; photo cards; hero detail; meta chips with ready-time;
  floating pill tab bar.
- New phase 4.5: ingredient toggle checklist feeding shopping list.
