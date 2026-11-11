import { useMemo, useState } from "react";
import type { Item, Receipt, Unit } from "../types";
import { IconBarcode, IconMinus, IconSearch } from "../components/Icons";
import Sheet from "../components/Sheet";
import ThemeToggle from "../components/ThemeToggle";
import ReceiptsView from "./ReceiptsView";

interface InventoryScreenProps {
  items: Item[];
  receipts: Receipt[];
  onConsume: (id: string, amount: number) => void;
  onMatchItem: (receiptId: string, itemId: string, productName: string) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

function formatQty(qty: number, unit: Unit) {
  return `${qty} ${unit}`;
}

export default function InventoryScreen({ items, receipts, onConsume, onMatchItem, theme, onToggleTheme }: InventoryScreenProps) {
  const [view, setView] = useState<"items" | "receipts">("items");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [selected, setSelected] = useState<Item | null>(null);

  const categories = useMemo(() => [...new Set(items.map((i) => i.category))], [items]);

  const filtered = items
    .filter((i) => (category === null ? true : i.category === category))
    .filter((i) => i.name.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => a.name.localeCompare(b.name));

  const selectedLive = selected ? items.find((i) => i.id === selected.id) ?? null : null;

  return (
    <div className="screen">
      <header className="screen-header">
        <h1 className="screen-title">{view === "items" ? "Inventory" : "Receipts"}</h1>
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </header>

      <div className="segmented">
        <button className={view === "items" ? "active" : ""} onClick={() => setView("items")}>
          Items
        </button>
        <button className={view === "receipts" ? "active" : ""} onClick={() => setView("receipts")}>
          Receipts
        </button>
      </div>

      {view === "receipts" ? (
        <ReceiptsView receipts={receipts} onMatchItem={onMatchItem} />
      ) : (
        <>
          <div className="search">
            <IconSearch size={18} />
            <input
              type="text"
              placeholder="Search items"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div className="chip-row">
            <button className={category === null ? "chip active" : "chip"} onClick={() => setCategory(null)}>
              All
            </button>
            {categories.map((c) => (
              <button key={c} className={category === c ? "chip active" : "chip"} onClick={() => setCategory(c)}>
                {c}
              </button>
            ))}
          </div>

          <div>
            {filtered.map((item) => (
              <button key={item.id} className="list-row" onClick={() => setSelected(item)}>
                <div className="info">
                  <div className="item-name">{item.name}</div>
                  <div className="item-sub">{item.category}</div>
                </div>
                <span className={item.quantity <= item.minQuantity ? "qty low" : "qty"}>
                  {formatQty(item.quantity, item.unit)}
                </span>
              </button>
            ))}
            {filtered.length === 0 && <div className="empty-state">No items match.</div>}
          </div>

          {selectedLive && (
            <Sheet onClose={() => setSelected(null)}>
              <h2 className="sheet-title">{selectedLive.name}</h2>
              <p className="sheet-sub">
                {selectedLive.category}
                {selectedLive.barcode ? ` · ${selectedLive.barcode}` : ""}
              </p>

              <div className="qty-stepper">
                <button onClick={() => onConsume(selectedLive.id, selectedLive.packageSize)} aria-label="Consume one package">
                  <IconMinus size={18} />
                </button>
                <span className="value">
                  {formatQty(selectedLive.quantity, selectedLive.unit)} in stock
                </span>
                <span style={{ width: 40 }} />
              </div>

              <div className="sheet-actions">
                <button className="btn btn-ghost" onClick={() => setSelected(null)}>
                  Close
                </button>
                <button
                  className="btn btn-primary"
                  onClick={() => {
                    onConsume(selectedLive.id, selectedLive.packageSize);
                    setSelected(null);
                  }}
                >
                  <IconBarcode size={16} />
                  Consume {selectedLive.packageSize} {selectedLive.unit}
                </button>
              </div>
            </Sheet>
          )}
        </>
      )}
    </div>
  );
}
