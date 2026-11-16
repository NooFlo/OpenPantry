export type Unit = "pcs" | "g" | "kg" | "ml" | "l";

/** "binary" = only in stock vs not in stock; "qty" = rounded stock count */
export type TrackingMode = "binary" | "qty";

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
  trackingMode: TrackingMode;
}

export interface ItemPatch {
  min_quantity?: number;
  package_size?: number;
  tracking_mode?: TrackingMode;
}

export interface Ingredient {
  id: string;
  raw: string;
  amount?: number;
  unit?: string;
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
  prepMinutes?: number;
  cookMinutes?: number;
  totalMinutes?: number;
  cuisine?: string;
  category?: string;
  tags?: string[];
  imageUrl?: string;
  createdAt?: string;
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

export type Tab = "home" | "inventory" | "receipts" | "recipes";

export interface ModelChoice {
  provider: "local" | "cloud";
  model: string;
}

export interface Settings {
  receiptsModel: ModelChoice;
  recipesModel: ModelChoice;
  cloudBaseUrl: string;
  cloudModel: string;
  cloudKeySet: boolean;
  haUrl: string;
  haEntity: string;
  haKeySet: boolean;
}

export interface SettingsPatch {
  receiptsModel?: ModelChoice;
  recipesModel?: ModelChoice;
  cloudBaseUrl?: string;
  cloudModel?: string;
  cloudApiKey?: string;
  haUrl?: string;
  haToken?: string;
  haEntity?: string;
}

export interface ModelList {
  local: string[];
  llmAvailable: boolean;
}
