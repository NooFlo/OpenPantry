import type { Item } from "../types";

export default function StockBar({ item }: { item: Item }) {
  const ratio = item.minQuantity > 0 ? item.quantity / (item.minQuantity * 2) : 1;
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  const low = item.quantity <= item.minQuantity;
  return (
    <div className="stock-bar">
      <div className={low ? "fill low" : "fill"} style={{ width: `${pct}%` }} />
    </div>
  );
}
