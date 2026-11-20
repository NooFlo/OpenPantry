import { useEffect, useState } from "react";
import type { Item, ItemPatch, ModelList, Recipe, RecipeEditPatch, Receipt, Settings, SettingsPatch, ShoppingListEntry, Tab } from "./types";
import {
  addMissingToShoppingList,
  addToShoppingList,
  confirmLow,
  consumeItem,
  deleteItem,
  deleteRecipe,
  editRecipe,
  fetchItems,
  fetchModels,
  fetchReceipts,
  fetchRecipes,
  fetchSettings,
  fetchShoppingList,
  addItemBarcode,
  matchRecipeIngredient,
  matchReceiptItem as matchReceiptItemApi,
  pushShoppingList,
  removeFromShoppingList,
  removeItemBarcode,
  restockItem,
  selectRecipeIngredient,
  updateItem,
  updateSettings,
} from "./api";
import TabBar from "./components/TabBar";
import Sidebar from "./components/Sidebar";
import HomeScreen from "./screens/HomeScreen";
import InventoryScreen from "./screens/InventoryScreen";
import RecipesScreen from "./screens/RecipesScreen";
import PlanningScreen from "./screens/PlanningScreen";

type Theme = "light" | "dark";

const DEFAULT_SETTINGS: Settings = {
  receiptsModel: { provider: "local", model: "qwen2.5:3b-instruct" },
  recipesModel: { provider: "local", model: "qwen2.5:3b-instruct" },
  cloudBaseUrl: "https://api.mistral.ai/v1",
  cloudModel: "mistral-small-latest",
  cloudKeySet: false,
  haUrl: "",
  haEntity: "todo.shopping_list",
  haKeySet: false,
  planningEnabled: true,
};

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
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [models, setModels] = useState<ModelList>({ local: [], llmAvailable: false });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!settings.planningEnabled && tab === "plan") setTab("home");
  }, [settings.planningEnabled, tab]);

  useEffect(() => {
    fetchItems().then(setItems);
    fetchShoppingList().then(setShoppingList).catch(console.error);
    fetchReceipts().then(setReceipts);
    fetchRecipes().then(setRecipes);
    fetchSettings().then(setSettings).catch(console.error);
    fetchModels().then(setModels).catch(console.error);
  }, []);

  const saveSettings = (patch: SettingsPatch) => {
    updateSettings(patch).then(setSettings).catch(console.error);
  };

  const consume = (id: string, amount: number) => {
    setItems((prev) =>
      prev.map((i) =>
        i.id === id
          ? i.trackingMode === "binary"
            ? { ...i, quantity: 0, uncertain: false }
            : { ...i, quantity: Math.max(0, Math.round((i.quantity - amount) * 1000) / 1000), uncertain: false }
          : i
      )
    );
    consumeItem(id, amount)
      .then(() => fetchShoppingList())
      .then(setShoppingList)
      .catch(console.error);
  };

  const restock = (id: string, amount: number) => {
    setItems((prev) =>
      prev.map((i) =>
        i.id === id
          ? { ...i, quantity: Math.round((i.quantity + amount) * 1000) / 1000, uncertain: false }
          : i
      )
    );
    restockItem(id, amount)
      .then(() => fetchShoppingList())
      .then(setShoppingList)
      .catch(console.error);
  };

  const confirmRunningLow = (id: string, isLow: boolean) => {
    setItems((prev) =>
      prev.map((i) =>
        i.id !== id ? i : isLow ? { ...i, quantity: 0, uncertain: false } : { ...i, uncertain: false }
      )
    );
    confirmLow(id, isLow)
      .then(() => fetchShoppingList())
      .then(setShoppingList)
      .catch(console.error);
  };

  const removeItem = (id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
    deleteItem(id)
      .then(() => fetchShoppingList())
      .then(setShoppingList)
      .catch(console.error);
  };

  const changeItemThresholds = (id: string, patch: ItemPatch) => {
    setItems((prev) =>
      prev.map((i) =>
        i.id === id
          ? {
              ...i,
              minQuantity: patch.min_quantity ?? i.minQuantity,
              packageSize: patch.package_size ?? i.packageSize,
              trackingMode: patch.tracking_mode ?? i.trackingMode,
            }
          : i
      )
    );
    updateItem(id, patch).catch(console.error);
  };

  const mergeItem = (updated: Item) =>
    setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));

  const onAddItemBarcode = (id: string, barcode: string) => {
    addItemBarcode(id, barcode).then(mergeItem).catch(console.error);
  };

  const onRemoveItemBarcode = (id: string, barcode: string) => {
    removeItemBarcode(id, barcode).then(mergeItem).catch(console.error);
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

  const addMissing = async (recipe: Recipe) => {
    const list = await addMissingToShoppingList(recipe.id, portions);
    setShoppingList(list);
    // the backend may have matched ingredient suggestions and created pantry items
    const [updatedItems, updatedRecipes] = await Promise.all([fetchItems(), fetchRecipes()]);
    setItems(updatedItems);
    setRecipes(updatedRecipes);
  };

  const matchReceiptItem = (receiptId: string, itemId: string, productName: string) => {
    matchReceiptItemApi(receiptId, itemId, productName)
      .then((updated) => {
        setReceipts((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
        return Promise.all([fetchItems(), fetchShoppingList()]);
      })
      .then(([updatedItems, list]) => {
        setItems(updatedItems);
        setShoppingList(list);
      })
      .catch(console.error);
  };

  const importRecipeToState = (recipe: Recipe) => {
    setRecipes((prev) => [...prev, recipe]);
  };

  const matchIngredient = (recipeId: string, ingredientId: string, itemName: string) => {
    matchRecipeIngredient(recipeId, ingredientId, itemName)
      .then((updated) => {
        setRecipes((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
        return fetchItems();
      })
      .then(setItems)
      .catch(console.error);
  };

  const saveRecipeEdit = (recipeId: string, patch: RecipeEditPatch) =>
    editRecipe(recipeId, patch).then((updated) => {
      setRecipes((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    });

  const removeRecipe = (recipeId: string) =>
    deleteRecipe(recipeId).then(() => {
      setRecipes((prev) => prev.filter((r) => r.id !== recipeId));
    });

  const selectIngredient = (recipeId: string, ingredientId: string) => {
    selectRecipeIngredient(recipeId, ingredientId)
      .then((updated) => setRecipes((prev) => prev.map((r) => (r.id === updated.id ? updated : r))))
      .catch(console.error);
  };

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  return (
    <div className="app">
      <Sidebar
        active={tab}
        onChange={setTab}
        theme={theme}
        onToggleTheme={toggleTheme}
        planningEnabled={settings.planningEnabled}
      />
      <main className="app-main">
        {tab === "home" && (
          <HomeScreen
            items={items}
            shoppingList={shoppingList}
            settings={settings}
            onToggleShoppingList={toggleShoppingList}
            onRemoveFromShoppingList={removeShoppingListEntry}
            onPushShoppingList={pushShoppingList}
            onSaveSettings={saveSettings}
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
            onRestock={restock}
            onDelete={removeItem}
            onMatchItem={matchReceiptItem}
            onUpdateItem={changeItemThresholds}
            onAddItemBarcode={onAddItemBarcode}
            onRemoveItemBarcode={onRemoveItemBarcode}
            settings={settings}
            models={models}
            onSaveSettings={saveSettings}
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
            onAddMissing={addMissing}
            onMatchIngredient={matchIngredient}
            onSelectIngredient={selectIngredient}
            onSaveRecipeEdit={saveRecipeEdit}
            onDeleteRecipe={removeRecipe}
            settings={settings}
            models={models}
            onSaveSettings={saveSettings}
            theme={theme}
            onToggleTheme={toggleTheme}
          />
        )}
        {tab === "plan" && settings.planningEnabled && (
          <PlanningScreen recipes={recipes} theme={theme} onToggleTheme={toggleTheme} />
        )}
      </main>
      <TabBar active={tab} onChange={setTab} planningEnabled={settings.planningEnabled} />
    </div>
  );
}
