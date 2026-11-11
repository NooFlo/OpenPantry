import type { Item, Recipe, Receipt } from "../types";

export const mockItems: Item[] = [
  { id: "salz", name: "Salz", category: "Pantry", quantity: 0.2, unit: "kg", minQuantity: 0.5, packageSize: 0.5, barcode: "4006434000937" },
  { id: "milch", name: "Milch", category: "Dairy", quantity: 0.4, unit: "l", minQuantity: 1, packageSize: 1, barcode: "4013165000110" },
  { id: "eier", name: "Eier", category: "Dairy", quantity: 3, unit: "pcs", minQuantity: 6, packageSize: 10 },
  { id: "kaffee", name: "Kaffee", category: "Pantry", quantity: 0, unit: "kg", minQuantity: 0.25, packageSize: 0.5, barcode: "4006400400222" },
  { id: "spuelmittel", name: "Spülmittel", category: "Household", quantity: 0.1, unit: "l", minQuantity: 0.3, packageSize: 0.5 },
  { id: "olivenoel", name: "Olivenöl", category: "Pantry", quantity: 0.7, unit: "l", minQuantity: 0.25, packageSize: 0.5 },
  { id: "reis", name: "Reis", category: "Pantry", quantity: 0.8, unit: "kg", minQuantity: 0.5, packageSize: 1 },
  { id: "butter", name: "Butter", category: "Dairy", quantity: 0.25, unit: "kg", minQuantity: 0.25, packageSize: 0.25, barcode: "4013165000111", uncertain: true },
  { id: "klopapier", name: "Toilettenpapier", category: "Household", quantity: 2, unit: "pcs", minQuantity: 4, packageSize: 10 },
  { id: "apfelsaft", name: "Apfelsaft", category: "Drinks", quantity: 3, unit: "l", minQuantity: 2, packageSize: 1 },
  { id: "mehl", name: "Mehl", category: "Pantry", quantity: 1.5, unit: "kg", minQuantity: 0.5, packageSize: 1 },
  { id: "zucker", name: "Zucker", category: "Pantry", quantity: 0.9, unit: "kg", minQuantity: 0.5, packageSize: 1 },
  { id: "spaghetti", name: "Spaghetti", category: "Pantry", quantity: 1, unit: "kg", minQuantity: 0.5, packageSize: 0.5 },
];

export const mockReceipts: Receipt[] = [
  {
    id: "r1",
    store: "REWE",
    date: "2025-06-14",
    total: 23.47,
    status: "done",
    items: [
      { id: "r1i1", rawName: "Bad Reichenhaller Jodarmes Salz", quantity: 1, suggestion: "Salz", status: "matched" },
      { id: "r1i2", rawName: "Weidemilch 3,8% 1l", quantity: 2, suggestion: "Milch", status: "matched" },
    ],
  },
  {
    id: "r2",
    store: "Lidl",
    date: "2025-06-16",
    total: 14.98,
    status: "review",
    items: [
      { id: "r2i1", rawName: "Bellmer Kartoffeln 2kg", quantity: 1, suggestion: "Kartoffeln", status: "pending" },
      { id: "r2i2", rawName: "Milbona Haltbarmilch 1,5%", quantity: 3, suggestion: "Milch", status: "pending" },
      { id: "r2i3", rawName: "Cien Duschgel", quantity: 1, status: "pending" },
    ],
  },
  {
    id: "r3",
    store: "Aldi",
    date: "2025-06-17",
    total: 31.12,
    status: "processing",
    items: [],
  },
];

export const mockRecipes: Recipe[] = [
  {
    id: "pancakes",
    title: "Pancakes",
    source: "pasted",
    basePortions: 4,
    ingredients: [
      { id: "p1", raw: "500 g Mehl", amount: 0.5, itemId: "mehl", tracked: true },
      { id: "p2", raw: "500 ml Milch", amount: 0.5, itemId: "milch", tracked: true },
      { id: "p3", raw: "3 Eier", amount: 3, itemId: "eier", tracked: true },
      { id: "p4", raw: "60 g Butter", amount: 0.06, itemId: "butter", tracked: true },
      { id: "p5", raw: "2 EL Zucker", amount: 0.05, itemId: "zucker", tracked: true },
      { id: "p6", raw: "1 Prise Salz", tracked: false },
    ],
    steps: [
      "Whisk flour, eggs, milk and sugar into a smooth batter.",
      "Let the batter rest for 15 minutes.",
      "Fry thin pancakes in butter until golden on both sides.",
    ],
  },
  {
    id: "aglio",
    title: "Spaghetti Aglio e Olio",
    source: "https://www.chefkoch.de/rezepte/aglio-e-olio",
    basePortions: 2,
    ingredients: [
      { id: "a1", raw: "250 g Spaghetti", amount: 0.25, itemId: "spaghetti", tracked: true },
      { id: "a2", raw: "6 EL Olivenöl", amount: 0.09, itemId: "olivenoel", tracked: true },
      { id: "a3", raw: "3 Zehen Knoblauch", tracked: true, suggestion: "Knoblauch" },
      { id: "a4", raw: "1 Handvoll Petersilie", tracked: true },
      { id: "a5", raw: "Salz", tracked: false },
    ],
    steps: [
      "Cook the spaghetti in salted water until al dente.",
      "Slowly warm sliced garlic in olive oil until golden.",
      "Toss pasta with the garlic oil and parsley.",
    ],
  },
  {
    id: "ruehrei",
    title: "Rührei",
    source: "pasted",
    basePortions: 2,
    ingredients: [
      { id: "e1", raw: "4 Eier", amount: 4, itemId: "eier", tracked: true },
      { id: "e2", raw: "20 g Butter", amount: 0.02, itemId: "butter", tracked: true },
      { id: "e3", raw: "Schuss Milch", amount: 0.05, itemId: "milch", tracked: true },
      { id: "e4", raw: "Salz, Pfeffer", tracked: false },
    ],
    steps: [
      "Beat the eggs with a splash of milk and salt.",
      "Melt butter in a pan over medium heat.",
      "Scramble slowly, removing from heat while still glossy.",
    ],
  },
];
