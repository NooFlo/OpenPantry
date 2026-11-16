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

/** Mode-aware stock label: "In stock" / "Not in stock", or a rounded count.
 *  Individual g/kg/ml amounts stay on record in the backend and are not
 *  surfaced here; qty mode shows a fixed round digit. */
export function formatStock(item: Item): string {
  if (isBinary(item)) return isInStock(item) ? "In stock" : "Not in stock";
  if (item.quantity > 0 && item.quantity < 1) return `<1 ${item.unit}`;
  return `${Math.round(item.quantity)} ${item.unit}`;
}
