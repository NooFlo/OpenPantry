export type Unit = "pcs" | "g" | "kg" | "ml" | "l";

export interface Item {
  id: string;
  name: string;
  category: string;
  quantity: number;
  unit: Unit;
  minQuantity: number;
  packageSize: number;
  barcode?: string;
  uncertain?: boolean;
}

export interface Ingredient {
  id: string;
  raw: string;
  amount?: number;
  itemId?: string;
  tracked: boolean;
  suggestion?: string;
}

export interface Recipe {
  id: string;
  title: string;
  source: string;
  basePortions: number;
  ingredients: Ingredient[];
  steps: string[];
}

export type ReceiptStatus = "processing" | "review" | "done";

export interface ReceiptItem {
  id: string;
  rawName: string;
  quantity: number;
  suggestion?: string;
  status: "matched" | "pending";
}

export interface Receipt {
  id: string;
  store: string;
  date: string;
  total: number;
  status: ReceiptStatus;
  items: ReceiptItem[];
}

export interface ShoppingListEntry {
  itemId: string;
  name: string;
  amount: number;
  unit: Unit;
}

export type Tab = "home" | "inventory" | "recipes";
