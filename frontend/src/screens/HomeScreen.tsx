import type { Item, ShoppingListEntry } from "../types";
import StockBar from "../components/StockBar";
import { IconCheck, IconPlus } from "../components/Icons";
import ThemeToggle from "../components/ThemeToggle";

interface HomeScreenProps {
  items: Item[];
  shoppingList: ShoppingListEntry[];
  onToggleShoppingList: (id: string) => void;
  onRemoveFromShoppingList: (id: string) => void;
  onConfirmLow: (id: string, isLow: boolean) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

export default function HomeScreen({
  items,
  shoppingList,
  onToggleShoppingList,
  onRemoveFromShoppingList,
  onConfirmLow,
  theme,
  onToggleTheme,
}: HomeScreenProps) {
  const lowStock = items.filter((i) => i.quantity <= i.minQuantity && !i.uncertain);
  const uncertain = items.filter((i) => i.uncertain);

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
          <div className="summary-value neutral">{shoppingList.length}</div>
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
          const added = shoppingList.some((e) => e.itemId === item.id);
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

      {uncertain.length > 0 && (
        <>
          <h2 className="section-title">Might be running low</h2>
          {uncertain.map((item) => (
            <div key={item.id} className="card item-card">
              <div className="info">
                <div className="item-name">{item.name}</div>
                <div className="item-sub">est. {item.quantity} {item.unit} left after cooking</div>
              </div>
              <div className="yn-row">
                <button className="btn btn-primary btn-sm" onClick={() => onConfirmLow(item.id, true)}>
                  Yes
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => onConfirmLow(item.id, false)}>
                  No
                </button>
              </div>
            </div>
          ))}
        </>
      )}

      {shoppingList.length > 0 && (
        <>
          <h2 className="section-title">Shopping list</h2>
          <div className="card">
            {shoppingList.map((entry) => (
              <div key={entry.itemId} className="sl-row">
                <div className="info">
                  <div className="item-name">{entry.name}</div>
                </div>
                <span className="qty">
                  +{entry.amount} {entry.unit}
                </span>
                <button className="icon-btn" aria-label={`Remove ${entry.name}`} onClick={() => onRemoveFromShoppingList(entry.itemId)}>
                  ×
                </button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
