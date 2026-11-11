import { useEffect, useState } from "react";
import type { Item, Recipe, Receipt, ShoppingListEntry, Tab } from "./types";
import { fetchItems, fetchReceipts, fetchRecipes } from "./api";
import TabBar from "./components/TabBar";
import HomeScreen from "./screens/HomeScreen";
import InventoryScreen from "./screens/InventoryScreen";
import RecipesScreen from "./screens/RecipesScreen";

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
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [portions, setPortions] = useState(2);
  const [shoppingList, setShoppingList] = useState<ShoppingListEntry[]>([]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    fetchItems().then(setItems);
    fetchReceipts().then(setReceipts);
    fetchRecipes().then(setRecipes);
  }, []);

  const consume = (id: string, amount: number) => {
    setItems((prev) =>
      prev.map((i) =>
        i.id === id
          ? { ...i, quantity: Math.max(0, Math.round((i.quantity - amount) * 1000) / 1000), uncertain: false }
          : i
      )
    );
  };

  const confirmLow = (id: string, isLow: boolean) => {
    setItems((prev) =>
      prev.map((i) =>
        i.id !== id ? i : isLow ? { ...i, quantity: 0, uncertain: false } : { ...i, uncertain: false }
      )
    );
  };

  const cook = (recipe: Recipe) => {
    setItems((prev) =>
      prev.map((item) => {
        const used = recipe.ingredients
          .filter((ing) => ing.tracked && ing.itemId === item.id && ing.amount != null)
          .reduce((sum, ing) => sum + ((ing.amount ?? 0) * portions) / recipe.basePortions, 0);
        if (used <= 0) return item;
        const quantity = Math.max(0, Math.round((item.quantity - used) * 1000) / 1000);
        return { ...item, quantity, uncertain: quantity <= item.minQuantity ? true : item.uncertain };
      })
    );
  };

  const toggleShoppingList = (id: string) => {
    const item = items.find((i) => i.id === id);
    if (!item) return;
    setShoppingList((prev) => {
      if (prev.some((e) => e.itemId === id)) return prev.filter((e) => e.itemId !== id);
      return [...prev, { itemId: id, name: item.name, amount: item.packageSize, unit: item.unit }];
    });
  };

  const removeFromShoppingList = (id: string) => {
    setShoppingList((prev) => prev.filter((e) => e.itemId !== id));
  };

  const addMissing = (recipe: Recipe) => {
    setShoppingList((prev) => {
      let next = [...prev];
      for (const ing of recipe.ingredients) {
        if (!ing.tracked || !ing.itemId || ing.amount == null) continue;
        const item = items.find((i) => i.id === ing.itemId);
        if (!item) continue;
        const required = (ing.amount * portions) / recipe.basePortions;
        const missing = required - item.quantity;
        if (missing <= 1e-9) continue;
        const packs = Math.ceil(missing / item.packageSize - 1e-9);
        const add = Math.round(packs * item.packageSize * 1000) / 1000;
        const existing = next.find((e) => e.itemId === item.id);
        if (existing) {
          next = next.map((e) =>
            e.itemId === item.id ? { ...e, amount: Math.round((e.amount + add) * 1000) / 1000 } : e
          );
        } else {
          next.push({ itemId: item.id, name: item.name, amount: add, unit: item.unit });
        }
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

  const importRecipeToState = (recipe: Recipe) => {
    setRecipes((prev) => [...prev, recipe]);
  };

  const matchRecipeIngredient = (recipeId: string, ingredientId: string, itemName: string) => {
    const item = items.find((i) => i.name.toLowerCase() === itemName.toLowerCase());
    if (!item) return;
    setRecipes((prev) =>
      prev.map((r) =>
        r.id !== recipeId
          ? r
          : {
              ...r,
              ingredients: r.ingredients.map((ing) =>
                ing.id === ingredientId
                  ? { ...ing, itemId: item.id, amount: ing.amount ?? item.packageSize, suggestion: undefined }
                  : ing
              ),
            }
          )
      );
  };

  const markUntracked = (recipeId: string, ingredientId: string) => {
    setRecipes((prev) =>
      prev.map((r) =>
        r.id !== recipeId
          ? r
          : {
              ...r,
              ingredients: r.ingredients.map((ing) =>
                ing.id === ingredientId ? { ...ing, tracked: false, suggestion: undefined } : ing
              ),
            }
          )
      );
  };

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  return (
    <>
      {tab === "home" && (
        <HomeScreen
          items={items}
          shoppingList={shoppingList}
          onToggleShoppingList={toggleShoppingList}
          onRemoveFromShoppingList={removeFromShoppingList}
          onConfirmLow={confirmLow}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      )}
      {tab === "inventory" && (
        <InventoryScreen
          items={items}
          receipts={receipts}
          onConsume={consume}
          onMatchItem={matchReceiptItem}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      )}
      {tab === "recipes" && (
        <RecipesScreen
          recipes={recipes}
          items={items}
          portions={portions}
          onPortionsChange={setPortions}
          onImport={importRecipeToState}
          onCook={cook}
          onAddMissing={addMissing}
          onMatchIngredient={matchRecipeIngredient}
          onMarkUntracked={markUntracked}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      )}
      <TabBar active={tab} onChange={setTab} />
    </>
  );
}
