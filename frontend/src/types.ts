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
  /** How much you buy per purchase (overrides package size on the shopping
   *  list). null = same as one package. */
  buyAmount?: number | null;
  /** Off by default: only these items land on the shopping list once empty. */
  autoRestock?: boolean;
  barcode?: string;
  /** All product barcodes that hit this item; `barcode` is the primary. */
  barcodes?: string[];
  /** Whole packages in stock (bottles, packs) — qty mode only, derived in
   *  the backend. Piece items count pieces; exact ml/g stay in `quantity`. */
  packageCount?: number | null;
  uncertain?: boolean;
  trackingMode: TrackingMode;
}

export interface ItemPatch {
  min_quantity?: number;
  package_size?: number;
  buy_amount?: number;
  auto_restock?: boolean;
  tracking_mode?: TrackingMode;
  barcode?: string;
}

export interface Ingredient {
  id: string;
  raw: string;
  amount?: number;
  unit?: string;
  itemId?: string;
  tracked: boolean;
  suggestion?: string;
  /** shared id of an "and/or" alternative group ("rice or naan") */
  altGroup?: string;
  /** the picked option of its group; only it is shopped/deducted */
  selected?: boolean;
}

/** A quantified ingredient mention in a step's text: the character span
 *  where it appears. The UI renders a live-scaled "(qty)" behind the span. */
export interface StepLink {
  ingredientId: string;
  start: number;
  end: number;
  name: string;
}

export interface Recipe {
  id: string;
  title: string;
  source: string;
  basePortions: number;
  ingredients: Ingredient[];
  steps: string[];
  /** one StepLink list per step, same order as `steps` */
  stepIngredients?: StepLink[][];
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

/** Manual recipe edit: one ingredient line from the edit form. An `id`
 *  present in the recipe with an unchanged `raw` keeps its match. */
export interface RecipeEditIngredient {
  id?: string;
  raw: string;
}

export interface RecipeEditPatch {
  title?: string;
  source?: string;
  base_portions?: number;
  ingredients?: RecipeEditIngredient[];
  steps?: string[];
}

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

export type Tab = "home" | "inventory" | "recipes" | "plan";

export interface PlanPerson {
  id: string;
  name: string;
}

export interface PlanningFill {
  id: string;
  mealId: string;
  recipeId?: string | null;
  recipeTitle?: string | null;
  preparedId?: string | null;
  preparedName?: string | null;
  personId?: string | null;
  personName?: string | null;
  portions: number;
  prepMultiplier: number;
}

export interface PlanningMeal {
  id: string;
  weekStart: string;
  day: number;
  meal: string;
  persons: PlanPerson[];
  fills: PlanningFill[];
}

export interface PreparedMeal {
  id: string;
  name: string;
  recipeId?: string | null;
  portions: number;
  manual: boolean;
  placed: number;
  available: number;
}

export interface WeekPlan {
  weekStart: string;
  persons: PlanPerson[];
  meals: PlanningMeal[];
  prepared: PreparedMeal[];
}

export interface PlanShoppingEntry {
  itemId?: string | null;
  name: string;
  amount: number;
  unit: Unit;
}

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
  planningEnabled: boolean;
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
  planningEnabled?: boolean;
}

export interface ModelList {
  local: string[];
  llmAvailable: boolean;
}

export interface PendingBarcode {
  barcode: string;
  /** null for OFF misses — the user names the product in the sheet. */
  name: string | null;
  /** True when Open Food Facts doesn't know this barcode at all. */
  offMiss?: boolean;
  brand?: string | null;
  quantity?: string | null;
  categories?: string[];
  imageUrl?: string | null;
  source?: string;
  suggestions: { id: string; name: string; reason: string }[];
}
