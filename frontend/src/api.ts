import type { Item, Receipt, Recipe, ShoppingListEntry } from "./types";

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

export function fetchReceipts(): Promise<Receipt[]> {
  return request<Receipt[]>("/receipts");
}

export function fetchRecipes(): Promise<Recipe[]> {
  return request<Recipe[]>("/recipes");
}

export function importRecipe(kind: "link" | "text", value: string): Promise<Recipe> {
  return request<Recipe>("/recipes/import", { method: "POST", body: JSON.stringify({ kind, value }) });
}

export function consumeItem(itemId: string, amount: number): Promise<Item> {
  return request<Item>(`/items/${itemId}/consume`, { method: "POST", body: JSON.stringify({ amount }) });
}

export function confirmLow(itemId: string, isLow: boolean): Promise<Item> {
  return request<Item>(`/items/${itemId}/confirm-low`, { method: "POST", body: JSON.stringify({ is_low: isLow }) });
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

export function markUntracked(recipeId: string, ingredientId: string): Promise<Recipe> {
  return request<Recipe>(`/recipes/${recipeId}/ingredients/${ingredientId}/untrack`, { method: "POST" });
}
