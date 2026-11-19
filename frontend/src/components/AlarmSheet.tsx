import { useEffect, useState } from "react";
import type { Item, ItemPatch } from "../types";
import Sheet from "./Sheet";
import StepperRow, { stepSize } from "./StepperRow";
import { IconBarcode, IconCheck } from "./Icons";
import { isBinary } from "../lib/tracking";

interface ItemSettingsProps {
  item: Item;
  onUpdate: (id: string, patch: ItemPatch) => void;
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

/** Tracking mode slider plus alarm/buy steppers. Rendered inline in the
 *  desktop split-detail pane and inside the AlarmSheet on mobile. */
export function ItemSettings({ item, onUpdate }: ItemSettingsProps) {
  const step = stepSize(item.unit);
  const minBuy = item.unit === "pcs" ? 1 : 0.1;
  const binary = isBinary(item);

  const [barcodeDraft, setBarcodeDraft] = useState(item.barcode ?? "");
  useEffect(() => setBarcodeDraft(item.barcode ?? ""), [item.id, item.barcode]);

  const saveBarcode = () => onUpdate(item.id, { barcode: barcodeDraft.trim() });

  const stepAlarm = (direction: -1 | 1) => {
    const next = Math.max(0, round(item.minQuantity + direction * step));
    onUpdate(item.id, { min_quantity: next });
  };

  const stepBuy = (direction: -1 | 1) => {
    const next = Math.max(minBuy, round(item.packageSize + direction * step));
    onUpdate(item.id, { package_size: next });
  };

  return (
    <>
      <div className="segmented" role="group" aria-label="Tracking mode">
        <button
          className={binary ? "active" : ""}
          onClick={() => onUpdate(item.id, { tracking_mode: "binary" })}
        >
          Binary
        </button>
        <button
          className={binary ? "" : "active"}
          onClick={() => onUpdate(item.id, { tracking_mode: "qty" })}
        >
          Quantity
        </button>
      </div>
      <p className="sheet-sub">
        {binary
          ? "Only tracks whether the item is in stock or not. The alarm fires when it is used up."
          : "Tracks a rounded stock count. Recipes compare their exact amounts against it."}
      </p>

      {!binary && (
        <StepperRow
          label="Alarm at"
          hint={item.minQuantity > 0 ? "Added automatically when stock falls to this" : "Disabled"}
          value={item.minQuantity}
          unit={item.unit}
          active={item.minQuantity > 0}
          onStep={stepAlarm}
        />
      )}

      <StepperRow
        label="Minimum buying quantity"
        hint="Shopping-list amount only; quick +/− steps by one"
        value={item.packageSize}
        unit={item.unit}
        active
        min={minBuy}
        onStep={stepBuy}
      />

      <div>
        <p className="sheet-sub">
          <IconBarcode size={14} /> Product barcode — the USB scanner uses it to
          track this item. Clear the field to remove the mapping.
        </p>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="import-input"
            style={{ marginBottom: 0, fontFamily: "monospace" }}
            inputMode="numeric"
            placeholder="e.g. 4006434000937"
            value={barcodeDraft}
            onChange={(e) => setBarcodeDraft(e.target.value)}
          />
          <button className="icon-btn" aria-label="Save barcode" onClick={saveBarcode}>
            <IconCheck size={18} />
          </button>
        </div>
      </div>
    </>
  );
}

interface AlarmSheetProps {
  item: Item;
  onUpdate: (id: string, patch: ItemPatch) => void;
  onClose: () => void;
}

export default function AlarmSheet({ item, onUpdate, onClose }: AlarmSheetProps) {
  return (
    <Sheet nested onClose={onClose}>
      <h2 className="sheet-title">{item.name}</h2>
      <p className="sheet-sub">Tracking, alarm &amp; buying quantity</p>
      <ItemSettings item={item} onUpdate={onUpdate} />
      <div className="sheet-actions">
        <button className="btn btn-ghost" onClick={onClose}>
          Done
        </button>
      </div>
    </Sheet>
  );
}
