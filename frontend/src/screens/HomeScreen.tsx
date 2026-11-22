import { useState } from "react";
import type { Item, Settings, SettingsPatch, ShoppingListEntry } from "../types";
import StockBar from "../components/StockBar";
import { IconCheck, IconGear, IconPlus } from "../components/Icons";
import AppSettingsSheet from "../components/AppSettingsSheet";
import ThemeToggle from "../components/ThemeToggle";
import ShoppingListSheet from "../components/ShoppingListSheet";
import { isBinary, isLow, packageCount } from "../lib/tracking";

interface HomeScreenProps {
  items: Item[];
  shoppingList: ShoppingListEntry[];
  settings: Settings;
  onToggleShoppingList: (id: string) => void;
  onRemoveFromShoppingList: (id: string) => void;
  onPushShoppingList: () => Promise<{ pushed: boolean }>;
  onSaveSettings: (patch: SettingsPatch) => void;
  onConfirmLow: (id: string, isLow: boolean) => void;
  onSnoozeLow: (id: string) => void;
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
  onSnoozeLow,
  theme,
  onToggleTheme,
}: HomeScreenProps) {
  const [showList, setShowList] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const lowStock = items.filter(
    (i) => isLow(i) && !i.uncertain && (i.autoRestock || i.minQuantity > 0)
  );
  const uncertain = items.filter((i) => i.uncertain);
  // Plan-driven dips: the stock covers today, but the meals on this week's
  // plan will pull it below the alarm. Ask, don't nag: "No" snoozes until
  // the estimate drops further.
  const projectedLow = items.filter((i) => i.lowProjected);

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
                          : item.unit === "pcs"
                            ? `${packageCount(item)} pcs / ${Math.max(0, Math.round(item.minQuantity))} pcs`
                            : `${packageCount(item)} pcs${item.minQuantity > 0 ? ` / ${Math.max(1, Math.round(item.minQuantity / (item.packageSize || 1)))} pcs` : ""}`}
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

          {projectedLow.length > 0 && (
            <>
              <h2 className="section-title">Will run low with your plan</h2>
              <div className="card-grid">
                {projectedLow.map((item) => (
                  <div key={item.id} className="card item-card">
                    <div className="info">
                      <div className="item-name">{item.name}</div>
                      <div className="item-sub">
                        {item.committed && item.committed > 0
                          ? `planned meals need ~${Math.round(item.committed * 100) / 100} ${item.unit}`
                          : "the week's plan will use up the stock"}
                      </div>
                    </div>
                    <div className="yn-row">
                      <button
                        className={shoppingList.some((e) => e.itemId === item.id)
                          ? "btn btn-primary btn-sm added"
                          : "btn btn-primary btn-sm"}
                        onClick={() => onToggleShoppingList(item.id)}
                      >
                        Yes, buy
                      </button>
                      <button className="btn btn-ghost btn-sm" onClick={() => onSnoozeLow(item.id)}>
                        Not now
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
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
                          : item.unit === "pcs"
                            ? `est. ${packageCount(item)} ${item.unit} left after cooking`
                            : `est. ${packageCount(item)} pcs left after cooking`}
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
