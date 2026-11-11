import type { Item, Receipt } from "./types";
import { mockItems, mockReceipts } from "./data/mock";

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function fetchItems(): Promise<Item[]> {
  await delay(150);
  return mockItems;
}

export async function fetchReceipts(): Promise<Receipt[]> {
  await delay(150);
  return mockReceipts;
}

export async function consumeItem(itemId: string, amount: number): Promise<void> {
  await delay(200);
  console.info(`consume ${amount} of ${itemId}`);
}

export async function addToShoppingList(itemId: string): Promise<void> {
  await delay(150);
  console.info(`add ${itemId} to shopping list`);
}

export async function removeFromShoppingList(itemId: string): Promise<void> {
  await delay(150);
  console.info(`remove ${itemId} from shopping list`);
}

export async function matchReceiptItem(receiptId: string, itemId: string, productName: string): Promise<void> {
  await delay(200);
  console.info(`match ${receiptId}/${itemId} to ${productName}`);
}
