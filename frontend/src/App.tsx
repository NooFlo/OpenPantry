import { useEffect, useState } from "react";
import type { Item, Recipe, Receipt, ShoppingListEntry, Tab } from "./types";
import {
  addMissingToShoppingList,
  addToShoppingList,
  confirmLow,
  consumeItem,
  cookRecipe,
  fetchItems,
  fetchReceipts,
  fetchRecipes,
  matchRecipeIngredient,
  markUntracked,
  removeFromShoppingList,
} from "./api";
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
    consumeItem(id, amount).catch(console.error);
  };

  const confirmRunningLow = (id: string, isLow: boolean) => {
    setItems((prev) =>
      prev.map((i) =>
        i.id !== id ? i : isLow ? { ...i, quantity: 0, uncertain: false } : { ...i, uncertain: false }
      )
    );
    confirmLow(id, isLow).catch(console.error);
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
    cookRecipe(recipe.id, portions).catch(console.error);
  };

  const toggleShoppingList = (id: string) => {
    const item = items.find((i) => i.id === id);
    if (!item) return;
    const call = shoppingList.some((e) => e.itemId === id)
      ? removeFromShoppingList(id)
      : addToShoppingList(id, item.packageSize);
    call.then(setShoppingList).catch(console.error);
  };

  const removeShoppingListEntry = (id: string) => {
    removeFromShoppingList(id).then(setShoppingList).catch(console.error);
  };

  const addMissing = (recipe: Recipe) => {
    addMissingToShoppingList(recipe.id, portions).then(setShoppingList).catch(console.error);
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

  const matchIngredient = (recipeId: string, ingredientId: string, itemName: string) => {
    matchRecipeIngredient(recipeId, ingredientId, itemName)
      .then((updated) => {
        setRecipes((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      })
      .catch(console.error);
  };

  const untrackIngredient = (recipeId: string, ingredientId: string) => {
    markUntracked(recipeId, ingredientId)
      .then((updated) => {
        setRecipes((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      })
      .catch(console.error);
  };

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  return (
    <>
      {tab === "home" && (
        <HomeScreen
          items={items}
          shoppingList={shoppingList}
          onToggleShoppingList={toggleShoppingList}
          onRemoveFromShoppingList={removeShoppingListEntry}
          onConfirmLow={confirmRunningLow}
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
          onMatchIngredient={matchIngredient}
          onMarkUntracked={untrackIngredient}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      )}
      <TabBar active={tab} onChange={setTab} />
    </>
  );
}
