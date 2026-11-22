import type { ControlCodeInfo, CustomLabelDesign, CustomLabelInfo, Item, ItemCreatePayload, ItemPatch, MissingGroup, MissingMergeResult, ModelList, PendingBarcode, PlanShoppingEntry, Receipt, Recipe, RecipeEditPatch, ScanLogEntry, Settings, SettingsPatch, ShoppingListEntry, WeekPlan } from "./types";

const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `${options?.method ?? "GET"} ${path} -> ${response.status}`);
  }
  return response.json();
}

export function fetchItems(): Promise<Item[]> {
  return request<Item[]>("/items");
}

export function fetchShoppingList(): Promise<ShoppingListEntry[]> {
  return request<ShoppingListEntry[]>("/shopping-list");
}

export function fetchReceipts(): Promise<Receipt[]> {
  return request<Receipt[]>("/receipts");
}

export function fetchRecipes(): Promise<Recipe[]> {
  return request<Recipe[]>("/recipes");
}

export function importRecipe(kind: "link" | "text", value: string): Promise<Recipe> {
  return request<Recipe>("/recipes/import", { method: "POST", body: JSON.stringify({ kind, value }) });
}

export function refreshRecipe(recipeId: string): Promise<Recipe> {
  return request<Recipe>(`/recipes/${recipeId}/refresh`, { method: "POST", body: "{}" });
}

export function consumeItem(itemId: string, amount: number): Promise<Item> {
  return request<Item>(`/items/${itemId}/consume`, { method: "POST", body: JSON.stringify({ amount }) });
}

export function restockItem(itemId: string, amount: number): Promise<Item> {
  return request<Item>(`/items/${itemId}/restock`, { method: "POST", body: JSON.stringify({ amount }) });
}

export function confirmLow(itemId: string, isLow: boolean): Promise<Item> {
  return request<Item>(`/items/${itemId}/confirm-low`, { method: "POST", body: JSON.stringify({ is_low: isLow }) });
}

/** Dismiss the projected low prompt until the estimate drops below its
 *  level at dismissal. */
export function snoozeLow(itemId: string): Promise<Item> {
  return request<Item>(`/items/${itemId}/snooze-low`, { method: "POST", body: "{}" });
}

export function updateItem(itemId: string, patch: ItemPatch): Promise<Item> {
  return request<Item>(`/items/${itemId}/update`, { method: "POST", body: JSON.stringify(patch) });
}

export function createItem(payload: ItemCreatePayload): Promise<Item> {
  return request<Item>("/items", { method: "POST", body: JSON.stringify(payload) });
}

/** Autocomplete suggestions for the tag picker ("zimt" -> Zimt, Zimtstangen…). */
export function searchConcepts(q: string): Promise<{ results: { conceptId: string; label: string; alias: string | null }[] }> {
  return request(`/catalog/search?q=${encodeURIComponent(q)}`);
}

/** Alias -> concept for the tag picker ("cinnamon sticks" -> Zimtstangen). */
export function resolveConcept(name: string): Promise<{ conceptId: string | null; label: string | null; family: string | null }> {
  return request(`/catalog/resolve?name=${encodeURIComponent(name)}`);
}

export function addItemBarcode(itemId: string, barcode: string): Promise<Item> {
  return request<Item>(`/items/${itemId}/barcodes`, { method: "POST", body: JSON.stringify({ barcode }) });
}

export function removeItemBarcode(itemId: string, barcode: string): Promise<Item> {
  return request<Item>(`/items/${itemId}/barcodes/${barcode}`, { method: "DELETE" });
}

export function deleteItem(itemId: string): Promise<Item> {
  return request<Item>(`/items/${itemId}`, { method: "DELETE" });
}

export function cookRecipe(recipeId: string, portions: number): Promise<Item[]> {
  return request<Item[]>(`/recipes/${recipeId}/cook`, { method: "POST", body: JSON.stringify({ portions }) });
}

export function addMissingToShoppingList(recipeId: string, portions: number): Promise<ShoppingListEntry[]> {
  return request<ShoppingListEntry[]>(`/recipes/${recipeId}/add-missing`, {
    method: "POST",
    body: JSON.stringify({ portions }),
  });
}

export function addToShoppingList(itemId: string, amount: number): Promise<ShoppingListEntry[]> {
  return request<ShoppingListEntry[]>(`/shopping-list/${itemId}`, {
    method: "POST",
    body: JSON.stringify({ amount }),
  });
}

export function removeFromShoppingList(itemId: string): Promise<ShoppingListEntry[]> {
  return request<ShoppingListEntry[]>(`/shopping-list/${itemId}`, { method: "DELETE" });
}

export function matchReceiptItem(receiptId: string, itemId: string, productName: string): Promise<Receipt> {
  return request<Receipt>(`/receipts/${receiptId}/items/${itemId}/match`, {
    method: "POST",
    body: JSON.stringify({ product_name: productName }),
  });
}

export function fetchMissingGroups(): Promise<MissingGroup[]> {
  return request<MissingGroup[]>("/recipes/missing-items");
}

export function mergeMissingGroup(key: string, itemId: string, name?: string): Promise<MissingMergeResult> {
  return request<MissingMergeResult>("/recipes/missing-items/merge", {
    method: "POST",
    body: JSON.stringify(name ? { key, item_id: itemId, name } : { key, item_id: itemId }),
  });
}

export function matchRecipeIngredient(recipeId: string, ingredientId: string, itemName: string): Promise<Recipe> {
  return request<Recipe>(`/recipes/${recipeId}/ingredients/${ingredientId}/match`, {
    method: "POST",
    body: JSON.stringify({ item_name: itemName }),
  });
}

export function selectRecipeIngredient(recipeId: string, ingredientId: string): Promise<Recipe> {
  return request<Recipe>(`/recipes/${recipeId}/ingredients/${ingredientId}/select`, {
    method: "POST",
    body: "{}",
  });
}

export function editRecipe(recipeId: string, patch: RecipeEditPatch): Promise<Recipe> {
  return request<Recipe>(`/recipes/${recipeId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteRecipe(recipeId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/recipes/${recipeId}`, { method: "DELETE" });
}

export function fetchSettings(): Promise<Settings> {
  return request<Settings>("/settings");
}

export function updateSettings(patch: SettingsPatch): Promise<Settings> {
  const body: Record<string, unknown> = {};
  if (patch.receiptsModel) body.receipts_model = patch.receiptsModel;
  if (patch.recipesModel) body.recipes_model = patch.recipesModel;
  if (patch.cloudBaseUrl !== undefined) body.cloud_base_url = patch.cloudBaseUrl;
  if (patch.cloudModel !== undefined) body.cloud_model = patch.cloudModel;
  if (patch.cloudApiKey !== undefined) body.cloud_api_key = patch.cloudApiKey;
  if (patch.haUrl !== undefined) body.ha_url = patch.haUrl;
  if (patch.haToken !== undefined) body.ha_token = patch.haToken;
  if (patch.haEntity !== undefined) body.ha_entity = patch.haEntity;
  if (patch.planningEnabled !== undefined) body.planning_enabled = patch.planningEnabled;
  if (patch.labelBaseUrl !== undefined) body.label_base_url = patch.labelBaseUrl;
  return request<Settings>("/settings", { method: "PUT", body: JSON.stringify(body) });
}

export function fetchWeekPlan(week: string): Promise<WeekPlan> {
  return request<WeekPlan>(`/plan?week=${encodeURIComponent(week)}`);
}

export function addPlanPerson(name: string): Promise<WeekPlan> {
  return request<WeekPlan>("/plan/persons", { method: "POST", body: JSON.stringify({ name }) });
}

export function deletePlanPerson(id: string): Promise<WeekPlan> {
  return request<WeekPlan>(`/plan/persons/${id}`, { method: "DELETE" });
}

export function addPlanMeal(week: string, day: number, meal: string, personIds: string[]): Promise<WeekPlan> {
  return request<WeekPlan>("/plan/meals", {
    method: "POST",
    body: JSON.stringify({ week, day, meal, person_ids: personIds }),
  });
}

export function togglePlanMealPerson(mealId: string, personId: string): Promise<WeekPlan> {
  return request<WeekPlan>(`/plan/meals/${mealId}/persons`, {
    method: "POST",
    body: JSON.stringify({ person_id: personId }),
  });
}

export function deletePlanMeal(mealId: string): Promise<WeekPlan> {
  return request<WeekPlan>(`/plan/meals/${mealId}`, { method: "DELETE" });
}

export function addPlanFill(
  mealId: string,
  fill: {
    recipeId?: string;
    preparedId?: string;
    portions: number;
    prepMultiplier: number;
    personId?: string;
    personIds?: string[];
  }
): Promise<WeekPlan> {
  return request<WeekPlan>(`/plan/meals/${mealId}/fills`, {
    method: "POST",
    body: JSON.stringify({
      recipe_id: fill.recipeId,
      prepared_id: fill.preparedId,
      portions: fill.portions,
      prep_multiplier: fill.prepMultiplier,
      person_id: fill.personId,
      person_ids: fill.personIds,
    }),
  });
}

export function deletePlanFill(fillId: string): Promise<WeekPlan> {
  return request<WeekPlan>(`/plan/fills/${fillId}`, { method: "DELETE" });
}

export function addPreparedMeal(name: string, portions: number): Promise<WeekPlan> {
  return request<WeekPlan>("/plan/prepared", {
    method: "POST",
    body: JSON.stringify({ name, portions }),
  });
}

export function deletePreparedMeal(id: string): Promise<WeekPlan> {
  return request<WeekPlan>(`/plan/prepared/${id}`, { method: "DELETE" });
}

export function fetchPlanShoppingList(week: string): Promise<PlanShoppingEntry[]> {
  return request<PlanShoppingEntry[]>(`/plan/${encodeURIComponent(week)}/shopping-list`);
}

export function pushPlanShoppingList(week: string): Promise<ShoppingListEntry[]> {
  return request<ShoppingListEntry[]>(`/plan/${encodeURIComponent(week)}/shopping-list/push`, {
    method: "POST",
    body: "{}",
  });
}

export function pushShoppingList(): Promise<{ pushed: boolean }> {
  return request<{ pushed: boolean }>("/shopping-list/push", { method: "POST", body: "{}" });
}

export function fetchModels(): Promise<ModelList> {
  return request<ModelList>("/models");
}

export function fetchPendingBarcodes(): Promise<PendingBarcode[]> {
  return request<{ barcodes: PendingBarcode[] }>("/barcode/pending").then((body) => body.barcodes);
}

export function assignBarcode(barcode: string, target: { itemId?: string; itemName?: string }): Promise<Item> {
  return request<Item>("/barcode/assign", {
    method: "POST",
    body: JSON.stringify({ barcode, item_id: target.itemId, item_name: target.itemName }),
  });
}

export interface ScanEvent {
  seq: number;
  kind: string;
  barcode: string;
}

export function fetchScanLog(): Promise<ScanLogEntry[]> {
  return request<{ scans: ScanLogEntry[] }>("/scan/recent?limit=100").then((body) => body.scans);
}

export function fetchScanEvents(since: number): Promise<{ seq: number; events: ScanEvent[] }> {
  return request<{ seq: number; events: ScanEvent[] }>(`/scan/events?since=${since}`);
}

export function discardPendingBarcode(barcode: string): Promise<{ discarded: string }> {
  return request(`/barcode/pending/${barcode}`, { method: "DELETE" });
}

// --------------------------------------------------------------- custom labels
// Per-item label designs (drag-and-drop editor) plus the editable
// BOUGHT/TRASH control-code stickers and their Epson exports.

/** Get a saved design payload for the API (elements omitted = "create with
 *  the tape's default preset" — the Create-custom-label checkbox). */
export function labelDesignPayload(design: Partial<CustomLabelDesign>) {
  return {
    elements: design.elements ?? null,
    widthMm: design.widthMm ?? 50,
    tape: design.tape ?? 24,
  };
}

export function fetchCustomLabelInfos(): Promise<CustomLabelInfo[]> {
  return request<CustomLabelInfo[]>("/labels/custom");
}

export function fetchItemCustomLabel(itemId: string): Promise<CustomLabelDesign> {
  return request<CustomLabelDesign>(`/labels/custom/item/${itemId}`);
}

export function saveItemCustomLabel(
  itemId: string,
  design: Partial<CustomLabelDesign>
): Promise<CustomLabelDesign> {
  return request<CustomLabelDesign>(`/labels/custom/item/${itemId}`, {
    method: "PUT",
    body: JSON.stringify(labelDesignPayload(design)),
  });
}

export function deleteItemCustomLabel(itemId: string): Promise<{ deleted: boolean }> {
  return request(`/labels/custom/item/${itemId}`, { method: "DELETE" });
}

export function fetchControlCustomLabel(control: string): Promise<CustomLabelDesign> {
  return request<CustomLabelDesign>(`/labels/custom/control/${control}`);
}

export function saveControlCustomLabel(
  control: string,
  design: Partial<CustomLabelDesign>
): Promise<CustomLabelDesign> {
  return request<CustomLabelDesign>(`/labels/custom/control/${control}`, {
    method: "PUT",
    body: JSON.stringify(labelDesignPayload(design)),
  });
}

export function fetchControlCodes(): Promise<ControlCodeInfo[]> {
  return request<ControlCodeInfo[]>("/labels/control-codes");
}

/** Live WYSIWYG preview of (unsaved) editor state, rendered by the backend
 *  with the exact print pipeline. Returns an object URL for an <img src>. */
export async function fetchLabelPreviewUrl(
  target: { kind: "item"; itemId: string } | { kind: "control"; control: string },
  design: CustomLabelDesign
): Promise<string> {
  const path = target.kind === "item"
    ? `/labels/preview/item/${target.itemId}`
    : `/labels/preview/control/${target.control}`;
  const response = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(labelDesignPayload(design)),
  });
  if (!response.ok) throw new Error(`label preview -> ${response.status}`);
  return URL.createObjectURL(await response.blob());
}

export const customLabelPngUrl = (itemId: string) => `/api/labels/custom/item/${itemId}/png`;
export const controlPngUrl = (control: string) => `/api/labels/custom/control/${control}/png`;
