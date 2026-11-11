import { useEffect, useState } from "react";
import type { Item, Receipt, Tab } from "./types";
import { fetchItems, fetchReceipts } from "./api";
import TabBar from "./components/TabBar";
import HomeScreen from "./screens/HomeScreen";
import InventoryScreen from "./screens/InventoryScreen";
import ReceiptsScreen from "./screens/ReceiptsScreen";

type Theme = "light" | "dark";

function initialTheme(): Theme {
  const stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const [tab, setTab] = useState<Tab>("home");
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [items, setItems] = useState<Item[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [shoppingList, setShoppingList] = useState<Set<string>>(new Set());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    fetchItems().then(setItems);
    fetchReceipts().then(setReceipts);
  }, []);

  const consume = (id: string, amount: number) => {
    setItems((prev) =>
      prev.map((i) => (i.id === id ? { ...i, quantity: Math.max(0, Math.round((i.quantity - amount) * 100) / 100) } : i))
    );
  };

  const toggleShoppingList = (id: string) => {
    setShoppingList((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const matchReceiptItem = (receiptId: string, itemId: string, productName: string) => {
    setReceipts((prev) =>
      prev.map((r) =>
        r.id !== receiptId
          ? r
          : {
              ...r,
              items: r.items.map((i) => (i.id === itemId ? { ...i, suggestion: productName, status: "matched" } : i)),
            }
      )
    );
  };

  return (
    <>
      {tab === "home" && (
        <HomeScreen
          items={items}
          shoppingList={shoppingList}
          onToggleShoppingList={toggleShoppingList}
          theme={theme}
          onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        />
      )}
      {tab === "inventory" && (
        <InventoryScreen
          items={items}
          onConsume={consume}
          theme={theme}
          onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        />
      )}
      {tab === "receipts" && (
        <ReceiptsScreen
          receipts={receipts}
          onMatchItem={matchReceiptItem}
          theme={theme}
          onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        />
      )}
      <TabBar active={tab} onChange={setTab} />
    </>
  );
}
