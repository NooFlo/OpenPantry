import { useEffect, useRef, useState } from "react";
import type { Item, ItemCreatePayload, ItemPatch, ModelList, PendingBarcode, Recipe, RecipeEditPatch, Receipt, ScanLogEntry, Settings, SettingsPatch, ShoppingListEntry, Tab } from "./types";
import {
  addMissingToShoppingList,
  addToShoppingList,
  confirmLow,
  consumeItem,
  deleteItem,
  deleteRecipe,
  editRecipe,
  assignBarcode,
  discardPendingBarcode,
  fetchItems,
  fetchModels,
  fetchPendingBarcodes,
  fetchScanEvents,
  fetchScanLog,
  fetchReceipts,
  fetchRecipes,
  fetchSettings,
  snoozeLow,
  fetchShoppingList,
  addItemBarcode,
  createItem,
  mergeMissingGroup,
  matchRecipeIngredient,
  matchReceiptItem as matchReceiptItemApi,
  pushShoppingList,
  removeFromShoppingList,
  removeItemBarcode,
  restockItem,
  selectRecipeIngredient,
  setRecipeFavorite,
  updateItem,
  updateSettings,
} from "./api";
import TabBar from "./components/TabBar";
import ReviewSheet from "./components/ReviewSheet";
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
  labelBaseUrl: "",
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
  const [pending, setPending] = useState<PendingBarcode[]>([]);
  const [scanLog, setScanLog] = useState<ScanLogEntry[]>([]);
  const [reviewOpen, setReviewOpen] = useState(false);
  const lastScanSeq = useRef(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!settings.planningEnabled && tab === "plan") setTab("home");
  }, [settings.planningEnabled, tab]);

  useEffect(() => {
    // baseline the scan-event sequence, then poll: any new unknown scan opens
    // the review sheet; scans waiting from before a reload reopen it too.
    fetchScanEvents(0)
      .then((body) => { lastScanSeq.current = body.seq; })
      .catch(() => { /* ignore */ });
    fetchPendingBarcodes().then((entries) => {
      setPending(entries);
      if (entries.length > 0) setReviewOpen(true);
    }).catch(() => { /* ignore */ });
    fetchScanLog().then(setScanLog).catch(() => { /* ignore */ });
    const tick = () => {
      fetchScanEvents(lastScanSeq.current)
        .then((body) => {
          if (body.seq === lastScanSeq.current) return;
          lastScanSeq.current = body.seq;
          // any scan restocked, created or emptied an item — pull the
          // fresh inventory and list without waiting for a page reload
          fetchItems().then(setItems).catch(() => { /* backend briefly away */ });
          fetchShoppingList().then(setShoppingList).catch(() => { /* ignore */ });
          fetchScanLog().then(setScanLog).catch(() => { /* ignore */ });
          return fetchPendingBarcodes().then((entries) => {
            setPending(entries);
            if (entries.length > 0) setReviewOpen(true);
          });
        })
        .catch(() => { /* backend briefly away */ });
    };
    const timer = window.setInterval(tick, 2000);
    return () => window.clearInterval(timer);
  }, []);

  const removePendingBarcode = async (barcode: string) => {
    await discardPendingBarcode(barcode).catch(console.error);
    const remaining = pending.filter((e) => e.barcode !== barcode);
    setPending(remaining);
    if (remaining.length === 0) setReviewOpen(false);
  };

  const closeReview = () => setReviewOpen(false);

  const reviewAssign = async (barcode: string, target: { itemId?: string; itemName?: string }) => {
    const item: Item = await assignBarcode(barcode, target);
    setItems((prev) => (prev.some((i) => i.id === item.id) ? prev.map((i) => (i.id === item.id ? item : i)) : [...prev, item]));
    setPending((prev) => prev.filter((e) => e.barcode !== barcode));
    if (pending.length === 1) setReviewOpen(false);
  };

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

  const mergeItem = (updated: Item) =>
    setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));

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
      .then((updated) => { mergeItem(updated); return fetchShoppingList(); })
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
      .then((updated) => { mergeItem(updated); return fetchShoppingList(); })
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

  // "Not now" on the projected prompt: hides it until the estimate drops
  // below its level at dismissal (planning more meals re-raises it).
  const snoozeRunningLow = (id: string) => {
    setItems((prev) => prev.map((i) => (i.id !== id ? i : { ...i, lowProjected: false })));
    snoozeLow(id).then(mergeItem).catch(console.error);
  };

  const removeItem = (id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id));
    deleteItem(id)
      .then(() => fetchShoppingList())
      .then(setShoppingList)
      .catch(console.error);
  };

  const renameItem = async (id: string, name: string) => {
    // optimistic rename; a rejection (e.g. 409 name taken) restores the truth
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, name } : i)));
    try {
      mergeItem(await updateItem(id, { name } as ItemPatch));
    } catch (error) {
      fetchItems().then(setItems).catch(console.error);
      throw error;
    }
  };

  const onAddItem = async (payload: ItemCreatePayload) => {
    const created = await createItem(payload);
    setItems((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
  };

  const changeItemThresholds = (id: string, patch: ItemPatch) => {
    setItems((prev) =>
      prev.map((i) =>
        i.id === id
          ? {
              ...i,
              minQuantity: patch.min_quantity ?? i.minQuantity,
              packageSize: patch.package_size ?? i.packageSize,
              buyAmount: patch.buy_amount ?? i.buyAmount,
              autoRestock: patch.auto_restock ?? i.autoRestock,
              trackingMode: patch.tracking_mode ?? i.trackingMode,
              name: patch.name ?? i.name,
              category: patch.category ?? i.category,
              conceptId: patch.concept_id !== undefined ? (patch.concept_id || null) : i.conceptId,
              conceptLabel:
                patch.concept_id !== undefined
                  ? patch.concept_id
                    ? i.conceptLabel
                    : null
                  : i.conceptLabel,
            }
          : i
      )
    );
    updateItem(id, patch).then(mergeItem).catch(console.error);
  };

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

  /** Settings > Missing items, merge: relink all rows of one food group
   *  onto an inventory item, then pull the fresh recipes + items. */
  const mergeMissing = async (key: string, itemId: string, name?: string) => {
    await mergeMissingGroup(key, itemId, name);
    const [updatedItems, updatedRecipes] = await Promise.all([fetchItems(), fetchRecipes()]);
    setItems(updatedItems);
    setRecipes(updatedRecipes);
  };

  /** Settings > Missing items, create: add the item, then link the group. */
  const createAndMergeMissing = async (key: string, payload: ItemCreatePayload) => {
    const created = await createItem(payload);
    setItems((prev) => [...prev, created]);
    // the food name the user settled on in the sheet is what the recipe
    // rows should read as — not necessarily the item's display name
    await mergeMissing(key, created.id, payload.name);
  };

  const saveRecipeEdit = (recipeId: string, patch: RecipeEditPatch) =>
    editRecipe(recipeId, patch).then((updated) => {
      setRecipes((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    });

  const removeRecipe = (recipeId: string) =>
    deleteRecipe(recipeId).then(() => {
      setRecipes((prev) => prev.filter((r) => r.id !== recipeId));
    });

  /** Star / un-star a recipe: optimistic, corrected from the API response. */
  const toggleRecipeFavorite = (recipeId: string, favorite: boolean) => {
    setRecipes((prev) => prev.map((r) => (r.id === recipeId ? { ...r, favorite } : r)));
    setRecipeFavorite(recipeId, favorite)
      .then((updated) => setRecipes((prev) => prev.map((r) => (r.id === updated.id ? updated : r))))
      .catch((err: unknown) => {
        console.error(err);
        // revert the optimistic flip
        setRecipes((prev) => prev.map((r) => (r.id === recipeId ? { ...r, favorite: !favorite } : r)));
      });
  };

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
            onSnoozeLow={snoozeRunningLow}
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
            onRenameItem={renameItem}
            onAddItem={onAddItem}
            onAddItemBarcode={onAddItemBarcode}
            onRemoveItemBarcode={onRemoveItemBarcode}
            scanLog={scanLog}
            onOpenReview={() => setReviewOpen(true)}
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
            onToggleFavorite={toggleRecipeFavorite}
            onMergeMissing={mergeMissing}
            onCreateMissingItem={createAndMergeMissing}
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

      {reviewOpen && (
        <ReviewSheet
          entries={pending}
          onAssign={reviewAssign}
          onRemove={removePendingBarcode}
          onClose={closeReview}
        />
      )}
    </div>
  );
}
