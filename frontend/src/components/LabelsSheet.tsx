import { useState } from "react";
import type { Item } from "../types";
import Sheet from "./Sheet";
import { IconBarcode } from "./Icons";

interface LabelsSheetProps {
  items: Item[];
  /** Item whose detail sheet is open, if any — gets a preview + one-tap strip. */
  selected: Item | null;
  onClose: () => void;
}

/** Same constants as the backend sticker page and the scanner bridge. */
const CONTROL_CODES = [
  { label: "BOUGHT", code: "2000000000008", hint: "Scans restock one package" },
  { label: "EMPTY / TRASH", code: "2000000000015", hint: "Scans zero the item and re-order it" },
  { label: "CONSUME", code: "2000000000022", hint: "Back to the default: one package used up" },
];

function TapeSelect({ tape, onChange }: { tape: 12 | 24; onChange: (tape: 12 | 24) => void }) {
  return (
    <div className="segmented" role="group" aria-label="Tape width">
      <button className={tape === 12 ? "active" : ""} onClick={() => onChange(12)}>12 mm</button>
      <button className={tape === 24 ? "active" : ""} onClick={() => onChange(24)}>24 mm</button>
    </div>
  );
}

function download(url: string) {
  window.location.assign(url);
}

/** Inventory settings submenu: scanner control codes and printable item
 *  labels (QR to the item's consume page + product barcode). Exports .lemd
 *  strips for the Epson Label Editor mobile app, like LabelGenerator does. */
export default function LabelsSheet({ items, selected, onClose }: LabelsSheetProps) {
  const [tape, setTape] = useState<12 | 24>(24);
  const allIds = items.map((i) => i.id).join(",");

  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title">Labels &amp; barcodes</h2>
      <p className="sheet-sub">
        Control codes for the USB scanner and shelf labels for the Epson label printer
      </p>

      <h3 className="sheet-title" style={{ fontSize: 16 }}>Tape width</h3>
      <TapeSelect tape={tape} onChange={setTape} />

      <h3 className="sheet-title" style={{ fontSize: 16 }}>Scanner control codes</h3>
      {CONTROL_CODES.map((mode) => (
        <div key={mode.code} className="sheet-sub" style={{ display: "flex", gap: 8 }}>
          <IconBarcode size={16} />
          <div>
            <strong>{mode.label}</strong>
            <div style={{ fontFamily: "monospace" }}>{mode.code}</div>
            <div>{mode.hint}</div>
          </div>
        </div>
      ))}
      <div className="sheet-actions">
        <button className="btn btn-ghost" onClick={() => window.open("/print/control-codes", "_blank")}>
          Print sheet (A4)
        </button>
        <button className="btn btn-primary" onClick={() => download(`/api/labels/control-codes.lemd?tape=${tape}`)}>
          Epson strip (.lemd)
        </button>
      </div>

      <h3 className="sheet-title" style={{ fontSize: 16 }}>Item labels</h3>
      {selected && (
        <>
          <p className="sheet-sub">
            {selected.name} — QR opens the item's consume page, the product barcode
            joins on 24 mm tape when set.
          </p>
          <img
            src={`/api/labels/item/${selected.id}/png?tape=${tape}`}
            alt={`Label preview for ${selected.name}`}
            style={{ maxWidth: "100%", height: "auto", borderRadius: 8 }}
          />
          <div className="sheet-actions">
            <button className="btn btn-primary" onClick={() => download(`/api/labels/items.lemd?ids=${selected.id}&tape=${tape}`)}>
              Epson strip: {selected.name}
            </button>
          </div>
        </>
      )}
      <div className="sheet-actions">
        <button className="btn" onClick={() => download(`/api/labels/items.lemd?ids=${allIds}&tape=${tape}`)}>
          Epson strip: all {items.length} items
        </button>
      </div>
      <p className="sheet-sub">
        The .lemd download opens in the Epson Label Editor app and prints over Bluetooth.
      </p>
    </Sheet>
  );
}
