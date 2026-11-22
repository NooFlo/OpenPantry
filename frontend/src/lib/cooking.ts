import type { Ingredient, Item, Recipe, StepLink } from "../types";
import { isBinary, isInStock } from "./tracking";

export function scaledAmount(ing: Ingredient, recipe: Recipe, portions: number): number | undefined {
  if (ing.amount == null) return undefined;
  return Math.round(((ing.amount * portions) / recipe.basePortions) * 1000) / 1000;
}

/** Rows measured in household words — spoons, cloves, cups, cm pieces
 *  ("0.5 TL Zimt"). Their amount scales with portions in displays and
 *  step qty mentions, but they are never compared numerically against an
 *  item's kg/l/pcs stock: stocked satisfies, empty is missing (mirrors
 *  repo.household_row on the backend). */
const HOUSEHOLD_UNITS = new Set([
  "tsp", "teaspoon", "teaspoons", "tbsp", "tbs", "tbsps", "tablespoon", "tablespoons",
  "el", "tl", "prise", "pinch", "handful", "handvoll", "splash", "sprig", "sprigs",
  "clove", "cloves", "zehe", "zehen", "pod", "pods", "stick", "sticks",
  "scheibe", "scheiben", "slice", "slices", "dose", "dosen", "can", "cans",
  "cup", "cups", "tasse", "tassen", "cm", "mm", "zoll", "inch", "stange", "stangen",
  "bund", "bunch", "beutel", "packung", "packungen", "glas",
]);

export function isHouseholdUnit(ing: Ingredient): boolean {
  const unit = (ing.unit || "").trim().toLowerCase();
  return !!unit && HOUSEHOLD_UNITS.has(unit);
}

/** Binary items cannot be divided into portions: in stock is always enough,
 *  out of stock blocks the recipe entirely. Alternative groups ("rice or
 *  naan") share one slot: satisfied if any option is available, and never
 *  block the recipe harder than the least available option would. */
function memberCapacity(ing: Ingredient, recipe: Recipe, items: Item[]): number | null {
  if (!ing.itemId) return null;
  const item = items.find((i) => i.id === ing.itemId);
  if (!item) return null;
  if (isBinary(item) || ing.amount == null || isHouseholdUnit(ing)) return isInStock(item) ? Infinity : null;
  const per = ing.amount / recipe.basePortions;
  if (per <= 0) return Infinity;
  return Math.floor(item.quantity / per + 1e-9);
}

export function maxPortions(recipe: Recipe, items: Item[]): number {
  let max = Infinity;
  const seenGroups = new Set<string>();
  for (const ing of recipe.ingredients) {
    if (!ing.tracked) continue;
    if (ing.altGroup) {
      if (seenGroups.has(ing.altGroup)) continue;
      seenGroups.add(ing.altGroup);
      // one of the options is enough to serve the recipe
      const members = recipe.ingredients.filter((i) => i.altGroup === ing.altGroup && i.tracked);
      let groupCap: number | null = null;
      for (const member of members) {
        const cap = memberCapacity(member, recipe, items);
        if (cap != null) groupCap = Math.max(groupCap ?? -Infinity, cap);
      }
      if (groupCap === null) return 0;
      max = Math.min(max, groupCap);
      continue;
    }
    if (!ing.itemId) return 0;
    const item = items.find((i) => i.id === ing.itemId);
    if (!item) return 0;
    if (isBinary(item)) {
      if (isInStock(item)) continue;
      return 0;
    }
    if (ing.amount == null || isHouseholdUnit(ing)) {
      // bare-name or household-measure row: no portion math possible —
      // stocked means unlimited, empty blocks the recipe
      // (mirrors memberCapacity/ingredientInStock)
      if (isInStock(item)) continue;
      return 0;
    }
    const per = ing.amount / recipe.basePortions;
    if (per <= 0) continue;
    max = Math.min(max, Math.floor(item.quantity / per + 1e-9));
  }
  return max;
}

export function isCookable(recipe: Recipe, items: Item[], portions: number): boolean {
  return maxPortions(recipe, items) >= portions;
}

export function missingCount(recipe: Recipe, items: Item[], portions: number): number {
  const seen = new Set<string>();
  let count = 0;
  for (const ing of recipe.ingredients) {
    if (!ing.tracked) continue;
    const key = ing.altGroup ?? ing.id;
    if (seen.has(key)) continue;
    seen.add(key);
    if (ing.altGroup) {
      // one slot per group: missing only when every option is missing
      const members = recipe.ingredients.filter((i) => i.altGroup === ing.altGroup && i.tracked);
      const anyOk = members.some((m) => {
        const item = m.itemId ? items.find((i) => i.id === m.itemId) : undefined;
        return item != null && ingredientInStock(m, recipe, portions, item);
      });
      if (members.length > 0 && !anyOk) count += 1;
      continue;
    }
    const item = ing.itemId ? items.find((i) => i.id === ing.itemId) : undefined;
    const ok = item != null && ingredientInStock(ing, recipe, portions, item);
    if (!ok) count += 1;
  }
  return count;
}

export function missingAmount(ing: Ingredient, recipe: Recipe, portions: number, item: Item): number {
  if (isBinary(item) || ing.amount == null || isHouseholdUnit(ing)) return 0;
  return Math.max(0, (ing.amount * portions) / recipe.basePortions - item.quantity);
}

/** Ingredient satisfied against the item's stock level, honoring its
 *  tracking mode: binary items only need to be in stock, qty items are
 *  compared against the exact recipe amount. Rows without an amount
 *  ("Weizenmehl (Type 550)" typed as a bare name) behave like binary
 *  items: stocked is satisfied, empty is missing. */
export function ingredientInStock(ing: Ingredient, recipe: Recipe, portions: number, item: Item): boolean {
  if (isBinary(item) || ing.amount == null || isHouseholdUnit(ing)) return isInStock(item);
  return missingAmount(ing, recipe, portions, item) <= 1e-9;
}

/** Smart quantity display: household units — below 1 kg/l shows g/ml ("0.06
 *  kg" -> "60 g"); pieces as plain numbers, "2" (or "2 pcs" with unit). */
export function formatQty(amount: number, unit?: string | null, withUnit = false): string {
  const trim = (n: number) => String(parseFloat((Math.round(n * 100) / 100).toFixed(2)));
  if (unit === "kg") return amount >= 1 ? `${trim(amount)} kg` : `${trim(amount * 1000)} g`;
  if (unit === "l") return amount >= 1 ? `${trim(amount)} l` : `${trim(amount * 1000)} ml`;
  return withUnit && unit ? `${trim(amount)} ${unit}` : trim(amount);
}

const AMOUNT_PREFIX_RE = /^[\d.,/\u00bd\u00bc\u00be\u2153\u2154\u215b]+(?:\s+[\d.,/\u00bd\u00bc\u00be\u2153\u2156\u2154\u215b]+)*\s*/;
const UNIT_TOKENS = new Set([
  "g", "gr", "gramm", "kg", "kilogramm", "ml", "milliliter", "cl", "l", "liter",
  "pcs", "piece", "pieces", "stück", "stueck", "stk", "st",
  "tl", "el", "esslöffel", "teelöffel", "prise", "pinch", "handful", "handvoll",
  "tsp", "tsps", "teaspoon", "teaspoons", "tbsp", "tbsps", "tablespoon", "tablespoons",
  "clove", "cloves", "zehe", "zehen", "bund", "bunch", "beutel", "packung", "packungen",
  "dose", "dosen", "can", "cans", "cup", "cups", "tasse", "tassen",
  "flasche", "flaschen", "stange", "stangen", "scheibe", "scheiben", "glas", "gläser",
]);

/** Bare ingredient display name from a raw line: amount, unit and paren-
 *  theticals stripped ("250 g Basmatireis (kalt)" -> "Basmatireis"). Keeps
 *  the raw fallback when nothing applies — never empties the name. */
export function baseIngredientName(raw: string): string {
  let name = raw.replace(/\([^)]*\)/g, " ").replace(/\s+/g, " ").trim();
  name = name.replace(AMOUNT_PREFIX_RE, "");
  const tokens = name.split(" ").filter(Boolean);
  while (tokens.length && UNIT_TOKENS.has(tokens[0].toLowerCase())) tokens.shift();
  const cleaned = tokens.join(" ").trim();
  return cleaned || raw.trim();
}

export interface StepSegment {
  text: string;
  /** live-scaled "(qty)" chip rendered after an ingredient mention */
  isQty?: boolean;
}

/** Step text sliced at the recorded ingredient mentions, with a formatted
 *  "(qty)" segment behind each — recomputed from the portions on every
 *  render, so the stepper updates all quantities live. */
export function stepSegments(
  step: string,
  links: StepLink[] | undefined,
  recipe: Recipe,
  portions: number
): StepSegment[] {
  const segments: StepSegment[] = [];
  let pos = 0;
  const ordered = [...(links ?? [])].sort((a, b) => a.start - b.start);
  for (const link of ordered) {
    if (link.start < pos || link.start < 0 || link.end > step.length) continue;
    const ing = recipe.ingredients.find((i) => i.id === link.ingredientId);
    const amount = ing ? scaledAmount(ing, recipe, portions) : undefined;
    segments.push({ text: step.slice(pos, link.end) });
    if (amount != null) segments.push({ text: ` (${formatQty(amount, ing?.unit)})`, isQty: true });
    pos = link.end;
  }
  segments.push({ text: step.slice(pos) });
  return segments;
}
