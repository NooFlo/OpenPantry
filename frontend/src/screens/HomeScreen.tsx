import { useState } from "react";
import type { Item, Settings, SettingsPatch, ShoppingListEntry } from "../types";
import StockBar from "../components/StockBar";
import { IconCheck, IconGear, IconPlus } from "../components/Icons";
import AppSettingsSheet from "../components/AppSettingsSheet";
import ThemeToggle from "../components/ThemeToggle";
import ShoppingListSheet from "../components/ShoppingListSheet";
import { isBinary, isLow } from "../lib/tracking";

interface HomeScreenProps {
  items: Item[];
  shoppingList: ShoppingListEntry[];
  settings: Settings;
  onToggleShoppingList: (id: string) => void;
  onRemoveFromShoppingList: (id: string) => void;
  onPushShoppingList: () => Promise<{ pushed: boolean }>;
  onSaveSettings: (patch: SettingsPatch) => void;
  onConfirmLow: (id: string, isLow: boolean) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

export default function HomeScreen({
  items,
  shoppingList,
  settings,
  onToggleShoppingList,
  onRemoveFromShoppingList,
  onPushShoppingList,
  onSaveSettings,
  onConfirmLow,
  theme,
  onToggleTheme,
}: HomeScreenProps) {
  const [showList, setShowList] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const lowStock = items.filter((i) => isLow(i) && !i.uncertain);
  const uncertain = items.filter((i) => i.uncertain);

  return (
    <div className="screen">
      <header className="screen-header">
        <h1 className="screen-title">Home</h1>
        <div className="header-actions">
          <button
            type="button"
            className="icon-btn"
            onClick={() => setShowSettings(true)}
            aria-label="Open settings"
          >
            <IconGear size={19} />
          </button>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </header>

      <div className="summary-row">
        <div className="card summary-card">
          <div className="summary-value">{lowStock.length}</div>
          <div className="summary-label">items low on stock</div>
        </div>
        <button
          type="button"
          className="card summary-card"
          onClick={() => setShowList(true)}
          aria-label="Show shopping list"
        >
          <div className="summary-value neutral">{shoppingList.length}</div>
          <div className="summary-label">on shopping list</div>
        </button>
      </div>

      <div className="home-grid">
        <div className="home-main">
          <h2 className="section-title">Low stock</h2>

          {lowStock.length === 0 ? (
            <div className="empty-state">
              Everything is stocked up.
              <br />
              Nothing to buy right now.
            </div>
          ) : (
            <div className="card-grid">
              {lowStock.map((item) => {
                const added = shoppingList.some((e) => e.itemId === item.id);
                return (
                  <div key={item.id} className="card item-card">
                    <div className="info">
                      <div className="item-name">{item.name}</div>
                      <div className="item-sub">
                        {isBinary(item)
                          ? "Not in stock"
                          : `${Math.round(item.quantity)} / ${item.minQuantity} ${item.unit}`}
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
              })}
            </div>
          )}

          {uncertain.length > 0 && (
            <>
              <h2 className="section-title">Might be running low</h2>
              <div className="card-grid">
                {uncertain.map((item) => (
                  <div key={item.id} className="card item-card">
                    <div className="info">
                      <div className="item-name">{item.name}</div>
                      <div className="item-sub">
                        {isBinary(item)
                          ? "May have been used while cooking"
                          : `est. ${item.quantity} ${item.unit} left after cooking`}
                      </div>
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
              </div>
            </>
          )}
        </div>

        {shoppingList.length > 0 && (
          <aside className="home-rail">
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
              <button type="button" className="btn btn-ghost btn-sm rail-sync" onClick={() => setShowList(true)}>
                Sync &amp; push
              </button>
            </div>
          </aside>
        )}
      </div>

      {showList && (
        <ShoppingListSheet
          entries={shoppingList}
          settings={settings}
          onRemove={onRemoveFromShoppingList}
          onSaveSettings={onSaveSettings}
          onPush={onPushShoppingList}
          onClose={() => setShowList(false)}
        />
      )}
      {showSettings && (
        <AppSettingsSheet
          settings={settings}
          onSave={onSaveSettings}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}
