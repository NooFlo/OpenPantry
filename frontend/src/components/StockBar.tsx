import type { Item } from "../types";
import { isBinary, isInStock } from "../lib/tracking";

export default function StockBar({ item }: { item: Item }) {
  if (isBinary(item)) {
    return (
      <div className="stock-bar">
        <div className={isInStock(item) ? "fill" : "fill low"} style={{ width: isInStock(item) ? "100%" : "0%" }} />
      </div>
    );
  }
  const ratio = item.minQuantity > 0 ? item.quantity / (item.minQuantity * 2) : 1;
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  const low = item.quantity <= item.minQuantity;
  return (
    <div className="stock-bar">
      <div className={low ? "fill low" : "fill"} style={{ width: `${pct}%` }} />
    </div>
  );
}
