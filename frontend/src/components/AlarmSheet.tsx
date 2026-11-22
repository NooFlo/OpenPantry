import { useEffect, useState } from "react";
import type { Item, ItemPatch } from "../types";
import { CANONICAL_CATEGORIES } from "../types";
import { resolveConcept } from "../api";
import Sheet from "./Sheet";
import StepperRow, { stepSize } from "./StepperRow";
import { IconBarcode, IconPlus, IconX } from "./Icons";
import { isBinary } from "../lib/tracking";

interface ItemSettingsProps {
  item: Item;
  onUpdate: (id: string, patch: ItemPatch) => void;
  onAddBarcode: (id: string, barcode: string) => void;
  onRemoveBarcode: (id: string, barcode: string) => void;
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

/** Tracking mode slider plus alarm/buy steppers. Rendered inline in the
 *  desktop split-detail pane and inside the AlarmSheet on mobile. */
export function ItemSettings({ item, onUpdate, onAddBarcode, onRemoveBarcode }: ItemSettingsProps) {
  const step = stepSize(item.unit);
  const minBuy = item.unit === "pcs" ? 1 : 0.1;
  const binary = isBinary(item);

  const [barcodeDraft, setBarcodeDraft] = useState("");
  const [conceptDraft, setConceptDraft] = useState("");
  const [conceptHint, setConceptHint] = useState<string | null>(null);
  const [conceptBusy, setConceptBusy] = useState(false);
  const [customCategory, setCustomCategory] = useState("");
  useEffect(() => {
    setBarcodeDraft("");
    setConceptDraft("");
    setConceptHint(null);
    setCustomCategory("");
  }, [item.id]);
  const barcodes = item.barcodes ?? (item.barcode ? [item.barcode] : []);
  const hasCustomCategory = item.category && !CANONICAL_CATEGORIES.includes(item.category);

  /** Look the typed alias up in the food catalog and tag the item. */
  const tagConcept = async () => {
    const query = conceptDraft.trim();
    if (!query || conceptBusy) return;
    setConceptBusy(true);
    setConceptHint(null);
    try {
      const { conceptId } = await resolveConcept(query);
      if (conceptId) {
        onUpdate(item.id, { concept_id: conceptId });
        setConceptDraft("");
      } else {
        setConceptHint(`No food tag found for “${query}”.`);
      }
    } catch {
      setConceptHint("Could not reach the catalog.");
    } finally {
      setConceptBusy(false);
    }
  };

  const addBarcode = () => {
    const code = barcodeDraft.trim();
    if (!code) return;
    onAddBarcode(item.id, code);
    setBarcodeDraft("");
  };

  const stepAlarm = (direction: -1 | 1) => {
    const next = Math.max(0, round(item.minQuantity + direction * step));
    onUpdate(item.id, { min_quantity: next });
  };

  const stepPackage = (direction: -1 | 1) => {
    const next = Math.max(minBuy, round(item.packageSize + direction * step));
    onUpdate(item.id, { package_size: next });
  };

  const buyValue = item.buyAmount ?? item.packageSize;
  const stepBuy = (direction: -1 | 1) => {
    const next = Math.max(minBuy, round(buyValue + direction * step));
    onUpdate(item.id, { buy_amount: next });
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

      <div className="stepper-row active" style={{ alignItems: "center" }}>
        <div style={{ flex: 1 }}>
          <div className="stepper-label">Always restock</div>
          <p className="stepper-hint" style={{ margin: 0 }}>
            Automatically added to the shopping list once empty. Without this
            or an alarm, an emptied item stays off the list and the homepage.
          </p>
        </div>
        <input
          type="checkbox"
          role="switch"
          aria-label="Always restock"
          style={{ width: 22, height: 22, accentColor: "var(--accent, #e8590c)" }}
          checked={!!item.autoRestock}
          onChange={(e) => onUpdate(item.id, { auto_restock: e.target.checked })}
        />
      </div>

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
        label="Package size"
        hint={binary
          ? undefined
          : "The size of one package — each scan adds or removes one of these"}
        value={item.packageSize}
        unit={item.unit}
        active
        min={minBuy}
        onStep={stepPackage}
      />

      {!binary && (
        <StepperRow
          label="Buy quantity"
          hint="How much you buy per purchase — the amount added to the shopping list"
          value={buyValue}
          unit={item.unit}
          active
          min={minBuy}
          onStep={stepBuy}
        />
      )}

      <div>
        <p className="sheet-sub">Category</p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {CANONICAL_CATEGORIES.map((cat) => (
            <button
              key={cat}
              className={`chip${item.category === cat ? " active" : ""}`}
              onClick={() => onUpdate(item.id, { category: cat })}
            >
              {cat}
            </button>
          ))}
          {hasCustomCategory && (
            <button
              className="chip active"
              title="Reset to Pantry"
              onClick={() => onUpdate(item.id, { category: "Pantry" })}
            >
              {item.category} ✕
            </button>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="import-input"
            style={{ marginBottom: 0 }}
            placeholder="custom category…"
            value={customCategory}
            onChange={(e) => setCustomCategory(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && customCategory.trim()) {
                onUpdate(item.id, { category: customCategory.trim() });
                setCustomCategory("");
              }
            }}
          />
          <button
            className="icon-btn"
            aria-label="Set custom category"
            disabled={!customCategory.trim()}
            onClick={() => {
              onUpdate(item.id, { category: customCategory.trim() });
              setCustomCategory("");
            }}
          >
            <IconPlus size={18} />
          </button>
        </div>
      </div>

      <div>
        <p className="sheet-sub">
          Food tag — which recipe ingredient this item is
        </p>
        {item.conceptId ? (
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
            <span className="tag-chip">{item.conceptLabel ?? item.conceptId}</span>
            <button
              className="icon-btn"
              aria-label="Remove food tag"
              title={"Cooking with this item counts as using up “" + (item.conceptLabel ?? item.conceptId) + "”"}
              onClick={() => onUpdate(item.id, { concept_id: "" })}
            >
              <IconX size={16} />
            </button>
          </div>
        ) : (
          <p className="sheet-sub" style={{ marginBottom: 8 }}>
            Not tagged yet — recipes can’t match this item by name alone.
          </p>
        )}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="import-input"
            style={{ marginBottom: 0 }}
            placeholder="find a tag: “cinnamon sticks”, “Zimt”…"
            value={conceptDraft}
            disabled={conceptBusy}
            onChange={(e) => setConceptDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") tagConcept();
            }}
          />
          <button
            className="icon-btn"
            aria-label="Tag item"
            disabled={conceptBusy || !conceptDraft.trim()}
            onClick={tagConcept}
          >
            <IconPlus size={18} />
          </button>
        </div>
        {conceptHint && (
          <p className="sheet-sub" style={{ marginTop: 6, marginBottom: 0 }}>{conceptHint}</p>
        )}
      </div>

      <div>
        <p className="sheet-sub">
          <IconBarcode size={14} /> Product barcodes — the USB scanner deducts
          and restocks this item with any of them, no matter which store the
          product came from.
        </p>
        {barcodes.map((code) => (
          <div key={code} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
            <span className="sheet-sub" style={{ fontFamily: "monospace", margin: 0, flex: 1 }}>
              {code}
            </span>
            <button className="icon-btn" aria-label={`Remove barcode ${code}`}
                    onClick={() => onRemoveBarcode(item.id, code)}>
              <IconX size={16} />
            </button>
          </div>
        ))}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="import-input"
            style={{ marginBottom: 0, fontFamily: "monospace" }}
            inputMode="numeric"
            placeholder="add another barcode…"
            value={barcodeDraft}
            onChange={(e) => setBarcodeDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") addBarcode();
            }}
          />
          <button className="icon-btn" aria-label="Add barcode" onClick={addBarcode}>
            <IconPlus size={18} />
          </button>
        </div>
      </div>
    </>
  );
}

interface AlarmSheetProps {
  item: Item;
  onUpdate: (id: string, patch: ItemPatch) => void;
  onAddBarcode: (id: string, barcode: string) => void;
  onRemoveBarcode: (id: string, barcode: string) => void;
  onClose: () => void;
}

export default function AlarmSheet({ item, onUpdate, onAddBarcode, onRemoveBarcode, onClose }: AlarmSheetProps) {
  return (
    <Sheet nested onClose={onClose}>
      <h2 className="sheet-title">{item.name}</h2>
      <p className="sheet-sub">Tracking, alarm &amp; buying quantity</p>
      <ItemSettings item={item} onUpdate={onUpdate} onAddBarcode={onAddBarcode} onRemoveBarcode={onRemoveBarcode} />
      <div className="sheet-actions">
        <button className="btn btn-ghost" onClick={onClose}>
          Done
        </button>
      </div>
    </Sheet>
  );
}
