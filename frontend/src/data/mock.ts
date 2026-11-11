import type { Item, Receipt } from "../types";

export const mockItems: Item[] = [
  { id: "salz", name: "Salz", category: "Pantry", quantity: 0.2, unit: "kg", minQuantity: 0.5, packageSize: 0.5, barcode: "4006434000937" },
  { id: "milch", name: "Milch", category: "Dairy", quantity: 0.4, unit: "l", minQuantity: 1, packageSize: 1, barcode: "4013165000110" },
  { id: "eier", name: "Eier", category: "Dairy", quantity: 3, unit: "pcs", minQuantity: 6, packageSize: 10 },
  { id: "kaffee", name: "Kaffee", category: "Pantry", quantity: 0, unit: "kg", minQuantity: 0.25, packageSize: 0.5, barcode: "4006400400222" },
  { id: "spuelmittel", name: "Spülmittel", category: "Household", quantity: 0.1, unit: "l", minQuantity: 0.3, packageSize: 0.5 },
  { id: "olivenoel", name: "Olivenöl", category: "Pantry", quantity: 0.7, unit: "l", minQuantity: 0.25, packageSize: 0.5 },
  { id: "reis", name: "Reis", category: "Pantry", quantity: 0.8, unit: "kg", minQuantity: 0.5, packageSize: 1 },
  { id: "butter", name: "Butter", category: "Dairy", quantity: 0.25, unit: "kg", minQuantity: 0.25, packageSize: 0.25, barcode: "4013165000111" },
  { id: "klopapier", name: "Toilettenpapier", category: "Household", quantity: 2, unit: "pcs", minQuantity: 4, packageSize: 10 },
  { id: "apfelsaft", name: "Apfelsaft", category: "Drinks", quantity: 3, unit: "l", minQuantity: 2, packageSize: 1 },
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
