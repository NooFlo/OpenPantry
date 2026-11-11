import type { Item } from "../types";
import StockBar from "../components/StockBar";
import { IconCheck, IconPlus } from "../components/Icons";
import ThemeToggle from "../components/ThemeToggle";

interface HomeScreenProps {
  items: Item[];
  shoppingList: Set<string>;
  onToggleShoppingList: (id: string) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

export default function HomeScreen({ items, shoppingList, onToggleShoppingList, theme, onToggleTheme }: HomeScreenProps) {
  const lowStock = items.filter((i) => i.quantity <= i.minQuantity);

  return (
    <div className="screen">
      <header className="screen-header">
        <h1 className="screen-title">Home</h1>
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </header>

      <div className="summary-row">
        <div className="card summary-card">
          <div className="summary-value">{lowStock.length}</div>
          <div className="summary-label">items low on stock</div>
        </div>
        <div className="card summary-card">
          <div className="summary-value neutral">{shoppingList.size}</div>
          <div className="summary-label">on shopping list</div>
        </div>
      </div>

      <h2 className="section-title">Low stock</h2>

      {lowStock.length === 0 ? (
        <div className="empty-state">
          Everything is stocked up.
          <br />
          Nothing to buy right now.
        </div>
      ) : (
        lowStock.map((item) => {
          const added = shoppingList.has(item.id);
          return (
            <div key={item.id} className="card item-card">
              <div className="info">
                <div className="item-name">{item.name}</div>
                <div className="item-sub">
                  {item.quantity} / {item.minQuantity} {item.unit}
                </div>
                <StockBar item={item} />
              </div>
              <button
                className={added ? "btn btn-primary added" : "btn btn-primary"}
                onClick={() => onToggleShoppingList(item.id)}
              >
                {added ? <IconCheck size={16} /> : <IconPlus size={16} />}
                {added ? "Added" : "Add"}
              </button>
            </div>
          );
        })
      )}
    </div>
  );
}
