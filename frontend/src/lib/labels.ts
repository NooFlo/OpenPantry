import type { ControlCodeInfo, CustomLabelDesign, Item, LabelElement, LabelField } from "../types";

/** Printable height in mm for each tape (mirrors the backend's
 *  labels.TAPE_GEOMETRY — labels are designed inside this strip). */
export const TAPE_PRINTABLE: Record<12 | 24, number> = { 12: 9.878, 24: 18.1 };

/** 1 pt in mm (1/72 inch) — element font sizes are set in points,
 *  LabelGenerator-style. */
export const PT_TO_MM = 0.352778;

/** Preset layouts (LabelGenerator's presets minus the Gridfinity one —
 *  pantry shelves, not workshop bins). Must stay in sync with the backend's
 *  labels.PRESETS / labels.DEFAULT_CONTROL_LAYOUT. */
export const LABEL_PRESETS: { id: string; label: string; design: CustomLabelDesign }[] = [
  {
    id: "mm12",
    label: "12 mm — name + QR",
    design: {
      tape: 12,
      widthMm: 50,
      elements: [
        { id: "name", field: "name", x: 1.1, y: 0.9, w: 37.5, h: 8, fontSizePt: 14, text: "" },
        { id: "qr", field: "qr", x: 39.9, y: 0.3, w: 9.3, h: 9.3, fontSizePt: 0, text: "" },
      ],
    },
  },
  {
    id: "mm24",
    label: "24 mm — big name + QR",
    design: {
      tape: 24,
      widthMm: 50,
      elements: [
        { id: "name", field: "name", x: 1.5, y: 2.2, w: 36.5, h: 13.5, fontSizePt: 29, text: "" },
        { id: "qr", field: "qr", x: 39, y: 4.5, w: 9.5, h: 9.5, fontSizePt: 0, text: "" },
      ],
    },
  },
  {
    id: "storage24",
    label: "24 mm — bin label",
    design: {
      tape: 24,
      widthMm: 50,
      elements: [
        { id: "name", field: "name", x: 2, y: 1.5, w: 20, h: 6.5, fontSizePt: 18, text: "" },
        { id: "category", field: "category", x: 2, y: 9.5, w: 31, h: 4.5, fontSizePt: 10, text: "" },
        { id: "note", field: "text", x: 2, y: 14.5, w: 31, h: 3.5, fontSizePt: 7, text: "" },
        { id: "qr", field: "qr", x: 23, y: 2, w: 10, h: 10, fontSizePt: 0, text: "" },
      ],
    },
  },
];

/** Default sticker design for the bought/trash control codes: caption +
 * the code graphic. Mirrors labels.DEFAULT_CONTROL_LAYOUT. */
export function defaultControlDesign(): CustomLabelDesign {
  return {
    tape: 24,
    widthMm: 50,
    elements: [
      { id: "caption", field: "name", x: 1.5, y: 1.2, w: 22, h: 5.5, fontSizePt: 15, text: "" },
      { id: "code", field: "ean", x: 1.5, y: 7.2, w: 46, h: 10.5, fontSizePt: 0, text: "" },
    ],
  };
}

/** Default design for a fresh item label (the tape's preset). */
export function defaultItemDesign(tape: 12 | 24): CustomLabelDesign {
  const preset = LABEL_PRESETS.find((p) => p.design.tape === tape) ?? LABEL_PRESETS[1];
  return {
    tape: preset.design.tape,
    widthMm: preset.design.widthMm,
    elements: preset.design.elements.map((el) => ({ ...el })),
  };
}

export let elementIdCounter = 0;
export function newElementId(): string {
  elementIdCounter += 1;
  return `el${Date.now().toString(36)}${elementIdCounter}`;
}

/** Field values a design resolves against — mirrors the backend's
 *  item_label_data / control_label_data so the editor canvas approximates
 *  the print (the exact render comes back as a PNG preview). */
export function fieldValues(
  target: { kind: "item"; item: Item } | { kind: "control"; control: ControlCodeInfo }
): Record<LabelField, string> {
  if (target.kind === "item") {
    const item = target.item;
    return {
      name: item.name,
      category: item.category,
      barcode: item.barcode ?? "",
      text: "",
      qr: `${window.location.origin}/c/${item.id}`,
      ean: item.barcode ?? "",
    };
  }
  const control = target.control;
  return {
    name: control.label,
    category: "",
    barcode: control.code,
    text: "",
    qr: control.code,
    ean: control.code,
  };
}

export function elementText(element: LabelElement, values: Record<LabelField, string>): string {
  if (element.field === "text") return element.text ?? "";
  return values[element.field] ?? "";
}

/** The printable strip height in mm for a design's tape. */
export function designHeightMm(design: CustomLabelDesign): number {
  return TAPE_PRINTABLE[design.tape === 12 ? 12 : 24];
}
