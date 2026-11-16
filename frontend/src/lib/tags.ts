// Canonical filter taxonomy, mirroring backend/app/extract.py CATEGORY_FILTERS.
// Recipes carry arbitrary source tags; only these get filter chips, the rest
// just show on the card/detail (same model Shopify uses on andy-cooks.com).

export const RECIPE_FILTERS = [
  "Quick",
  "Chicken",
  "Beef",
  "Pasta",
  "Fish and Seafood",
  "Vegetarian",
  "Comfort Food",
  "Slow Cooked",
  "BBQ",
  "Burgers and Sandwiches",
  "Curry",
  "Noodles",
  "Pork",
  "Lamb",
  "Dessert",
  "Breakfast",
  "Salad",
  "Soup",
] as const;

export type RecipeFilter = (typeof RECIPE_FILTERS)[number];

export function formatMinutes(minutes?: number): string | null {
  if (minutes == null || minutes <= 0) return null;
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m ? `${h}h ${m}m` : `${h}h`;
}
