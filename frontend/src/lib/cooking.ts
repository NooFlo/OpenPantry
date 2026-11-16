import type { Ingredient, Item, Recipe } from "../types";
import { isBinary, isInStock } from "./tracking";

export function scaledAmount(ing: Ingredient, recipe: Recipe, portions: number): number | undefined {
  if (ing.amount == null) return undefined;
  return Math.round(((ing.amount * portions) / recipe.basePortions) * 1000) / 1000;
}

/** Binary items cannot be divided into portions: in stock is always enough,
 *  out of stock blocks the recipe entirely. */
export function maxPortions(recipe: Recipe, items: Item[]): number {
  let max = Infinity;
  for (const ing of recipe.ingredients) {
    if (!ing.tracked) continue;
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
  return recipe.ingredients.filter((ing) => {
    if (!ing.tracked) return false;
    if (!ing.itemId || ing.amount == null) return true;
    const item = items.find((i) => i.id === ing.itemId);
    if (!item) return true;
    if (isBinary(item)) return !isInStock(item);
    const required = (ing.amount * portions) / recipe.basePortions;
    return item.quantity < required - 1e-9;
  }).length;
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
