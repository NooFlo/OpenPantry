import type { Item, ItemPatch, ModelList, Receipt, Recipe, RecipeEditPatch, Settings, SettingsPatch, ShoppingListEntry } from "./types";

const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(`${options?.method ?? "GET"} ${path} -> ${response.status}`);
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

export function updateItem(itemId: string, patch: ItemPatch): Promise<Item> {
  return request<Item>(`/items/${itemId}/update`, { method: "POST", body: JSON.stringify(patch) });
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
  return request<Settings>("/settings", { method: "PUT", body: JSON.stringify(body) });
}

export function pushShoppingList(): Promise<{ pushed: boolean }> {
  return request<{ pushed: boolean }>("/shopping-list/push", { method: "POST", body: "{}" });
}

export function fetchModels(): Promise<ModelList> {
  return request<ModelList>("/models");
}
