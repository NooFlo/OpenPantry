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

export type Tab = "home" | "inventory" | "receipts";
