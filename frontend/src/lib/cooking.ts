import type { Ingredient, Item, Recipe } from "../types";
import { isBinary, isInStock } from "./tracking";

export function scaledAmount(ing: Ingredient, recipe: Recipe, portions: number): number | undefined {
  if (ing.amount == null) return undefined;
  return Math.round(((ing.amount * portions) / recipe.basePortions) * 1000) / 1000;
}

/** Binary items cannot be divided into portions: in stock is always enough,
 *  out of stock blocks the recipe entirely. Alternative groups ("rice or
 *  naan") share one slot: satisfied if any option is available, and never
 *  block the recipe harder than the least available option would. */
function memberCapacity(ing: Ingredient, recipe: Recipe, items: Item[]): number | null {
  if (!ing.itemId) return null;
  const item = items.find((i) => i.id === ing.itemId);
  if (!item) return null;
  if (isBinary(item)) return isInStock(item) ? Infinity : null;
  if (ing.amount == null) return isInStock(item) ? Infinity : null;
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
    if (!ing.itemId || ing.amount == null) return 0;
    const item = items.find((i) => i.id === ing.itemId);
    if (!item) return 0;
    if (isBinary(item)) {
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
    const ok = item != null && ing.amount != null && ingredientInStock(ing, recipe, portions, item);
    if (!ok) count += 1;
  }
  return count;
}

export function missingAmount(ing: Ingredient, recipe: Recipe, portions: number, item: Item): number {
  if (isBinary(item)) return 0;
  if (ing.amount == null) return 0;
  return Math.max(0, (ing.amount * portions) / recipe.basePortions - item.quantity);
}

/** Ingredient satisfied against the item's stock level, honoring its
 *  tracking mode: binary items only need to be in stock, qty items are
 *  compared against the exact recipe amount. */
export function ingredientInStock(ing: Ingredient, recipe: Recipe, portions: number, item: Item): boolean {
  if (isBinary(item)) return isInStock(item);
  return missingAmount(ing, recipe, portions, item) <= 1e-9;
}
