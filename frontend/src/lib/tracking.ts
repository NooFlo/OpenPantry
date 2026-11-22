import type { Item } from "../types";

export function isBinary(item: Item): boolean {
  return item.trackingMode === "binary";
}

export function isInStock(item: Item): boolean {
  return item.quantity > 0;
}

export function isLow(item: Item): boolean {
  return isBinary(item) ? !isInStock(item) : item.quantity <= item.minQuantity;
}

/** Whole packages in stock: bottles for juice, pieces for eggs. Piece-tracked
 *  items count their pieces (`packageCount` already equals them); volume- or
 *  weight-tracked items count packages. Exact ml/g amounts stay on record in
 *  the backend — only the display is whole-numbered. */
export function packageCount(item: Item): number {
  if (item.packageCount != null) return item.packageCount;
  if (item.unit === "pcs") return Math.round(item.quantity);
  return Math.round(item.quantity / (item.packageSize || 1));
}

/** One package as a physical amount: "Use one" removes a whole bottle for
 *  l/kg items, but a single piece for pcs items (their packageSize is the
 *  buy size, not the display count). */
export function stepAmount(item: Item): number {
  return item.unit === "pcs" ? 1 : item.packageSize || 1;
}

/** Mode-aware stock label: "In stock" / "Not in stock", or whole counts.
 *  Every qty item counts whole pieces — packets, bottles, packs. No
 *  fractional liters or grams anywhere. */
export function formatStock(item: Item): string {
  if (isBinary(item)) return isInStock(item) ? "In stock" : "Not in stock";
  if (item.quantity > 0 && item.quantity < 1 && item.unit === "pcs") {
    return `<1 ${item.unit}`;
  }
  return `${packageCount(item)} pcs`;
}

/** The alarm threshold as whole pieces/packages — what the user sets and
 *  sees; internally min_quantity stays physical. */
export function alarmCount(item: Item): number {
  if (item.minQuantity <= 0) return 0;
  if (item.unit === "pcs") return Math.round(item.minQuantity);
  return Math.max(1, Math.round(item.minQuantity / (item.packageSize || 1)));
}
