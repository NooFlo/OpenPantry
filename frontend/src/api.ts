import type { Item, Receipt, Recipe } from "./types";
import { mockItems, mockReceipts, mockRecipes } from "./data/mock";

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function fetchItems(): Promise<Item[]> {
  await delay(150);
  return mockItems;
}

export async function fetchReceipts(): Promise<Receipt[]> {
  await delay(150);
  return mockReceipts;
}

export async function fetchRecipes(): Promise<Recipe[]> {
  await delay(150);
  return mockRecipes;
}

export async function importRecipe(kind: "link" | "text", value: string): Promise<Recipe> {
  await delay(600);
  return {
    id: `imported-${Date.now()}`,
    title: "Ofengemüse mit Feta",
    source: kind === "link" ? value : "pasted",
    basePortions: 2,
    ingredients: [
      { id: "i1", raw: "500 g Kartoffeln", amount: 0.5, tracked: true },
      { id: "i2", raw: "3 EL Olivenöl", amount: 0.045, itemId: "olivenoel", tracked: true, suggestion: "Olivenöl" },
      { id: "i3", raw: "1 TL Salz", amount: 0.01, tracked: true, suggestion: "Salz" },
      { id: "i4", raw: "200 g Feta", amount: 0.2, tracked: true },
      { id: "i5", raw: "1 TL getrockneter Oregano", tracked: false },
    ],
    steps: [
      "Cut the vegetables into bite-sized pieces.",
      "Toss with olive oil, salt and oregano on a tray.",
      "Roast at 200 °C for 30 minutes, then add feta for 10 more.",
    ],
  };
}

export async function consumeItem(itemId: string, amount: number): Promise<void> {
  await delay(200);
  console.info(`consume ${amount} of ${itemId}`);
}

export async function cookRecipe(recipeId: string): Promise<void> {
  await delay(150);
  console.info(`cooked ${recipeId}, deducting ingredients`);
}

export async function addToShoppingList(itemId: string, amount: number): Promise<void> {
  await delay(150);
  console.info(`add ${amount} of ${itemId} to shopping list`);
}

export async function removeFromShoppingList(itemId: string): Promise<void> {
  await delay(150);
  console.info(`remove ${itemId} from shopping list`);
}

export async function matchReceiptItem(receiptId: string, itemId: string, productName: string): Promise<void> {
  await delay(200);
  console.info(`match ${receiptId}/${itemId} to ${productName}`);
}
