import { useMemo, useState } from "react";
import type { ItemCreatePayload, Unit } from "../types";
import { CANONICAL_CATEGORIES } from "../types";
import { resolveConcept } from "../api";
import Autocomplete from "./Autocomplete";
import Sheet from "./Sheet";
import StepperRow, { stepSize } from "./StepperRow";
import { IconX } from "./Icons";
import { useConceptSearch } from "../lib/useConceptSearch";

const UNITS: Unit[] = ["g", "kg", "ml", "l", "pcs"];

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

interface AddItemSheetProps {
  onAddItem: (payload: ItemCreatePayload) => Promise<void>;
  onClose: () => void;
  /** Categories already in use — autocomplete suggestions. */
  categories?: string[];
}

/** Manual item creation with every attribute: name, category, tag,
 *  tracking mode, stock and alarm thresholds, package sizes, barcode. */
export default function AddItemSheet({ onAddItem, onClose, categories }: AddItemSheetProps) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("Pantry");
  const [customCategory, setCustomCategory] = useState("");
  const [unit, setUnit] = useState<Unit>("pcs");
  const [binary, setBinary] = useState(true);
  const [stock, setStock] = useState(1);
  const [packageSize, setPackageSize] = useState(1);
  const [buyQty, setBuyQty] = useState(1);
  const [alarmQty, setAlarmQty] = useState(0);
  const [barcode, setBarcode] = useState("");
  const [conceptId, setConceptId] = useState<string | null>(null);
  const [conceptLabel, setConceptLabel] = useState<string | null>(null);
  const [conceptDraft, setConceptDraft] = useState("");
  const [conceptHint, setConceptHint] = useState<string | null>(null);
  const [conceptBusy, setConceptBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const step = stepSize(unit);
  const finalCategory = customCategory.trim() || category;

  const conceptSearch = useConceptSearch(conceptDraft);
  const conceptSuggestions = conceptSearch.map((c) => ({
    key: c.conceptId,
    title: c.label,
    hint: c.alias ?? undefined,
  }));
  const categorySuggestions = useMemo(
    () =>
      (categories ?? CANONICAL_CATEGORIES)
        .filter(
          (c) =>
            c !== finalCategory &&
            c.toLowerCase().includes(customCategory.trim().toLowerCase())
        )
        .slice(0, 8)
        .map((c) => ({ key: c, title: c })),
    [categories, customCategory, finalCategory]
  );

  /** Look the typed alias up in the food catalog. */
  const findConcept = async () => {
    const query = conceptDraft.trim();
    if (!query || conceptBusy) return;
    setConceptBusy(true);
    setConceptHint(null);
    try {
      const result = await resolveConcept(query);
      if (result.conceptId) {
        setConceptId(result.conceptId);
        setConceptLabel(result.label);
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

  const submit = async () => {
    if (!name.trim()) {
      setError("Give the item a name.");
      return;
    }
    const payload: ItemCreatePayload = {
      name: name.trim(),
      category: finalCategory,
      unit,
      tracking_mode: binary ? "binary" : "qty",
      quantity: binary ? (stock > 0 ? 1 : 0) : stock,
      package_size: Math.max(0.0001, packageSize),
      buy_amount: Math.max(0.0001, buyQty),
      min_quantity: binary ? undefined : alarmQty,
      barcode: barcode.trim() || undefined,
      concept_id: conceptId ?? undefined,
    };
    setBusy(true);
    setError(null);
    try {
      await onAddItem(payload);
      onClose();
    } catch (requestError) {
      setError(String((requestError as Error).message ?? requestError));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet nested onClose={onClose}>
      <h2 className="sheet-title">Add item</h2>
      <p className="sheet-sub">Everything except the name is optional — sensible defaults apply.</p>

      <input
        className="import-input"
        placeholder="Item name, e.g. “Basmatireis 1 kg”"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />

      <p className="sheet-sub">Category</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {CANONICAL_CATEGORIES.map((cat) => (
          <button
            key={cat}
            className={`chip${finalCategory === cat ? " active" : ""}`}
            onClick={() => {
              setCategory(cat);
              setCustomCategory("");
            }}
          >
            {cat}
          </button>
        ))}
        {customCategory.trim() && (
          <button className="chip active" title="Clear custom category" onClick={() => setCustomCategory("")}>
            {customCategory.trim()} ✕
          </button>
        )}
      </div>
      <div style={{ marginTop: 8 }}>
        <Autocomplete
          className="import-input"
          inputStyle={{ marginBottom: 0 }}
          placeholder="…or type a category (new ones welcome)"
          value={customCategory}
          onChange={setCustomCategory}
          suggestions={categorySuggestions}
          onSelect={(s) => {
            setCategory(s.title);
            setCustomCategory("");
          }}
        />
      </div>

      <p className="sheet-sub">Food tag (optional — found automatically from the name if left alone)</p>
      {conceptId ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
          <span className="tag-chip">{conceptLabel ?? conceptId}</span>
          <button
            className="icon-btn"
            aria-label="Remove food tag"
            onClick={() => {
              setConceptId(null);
              setConceptLabel(null);
            }}
          >
            <IconX size={16} />
          </button>
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Autocomplete
          className="import-input"
          inputStyle={{ marginBottom: 0 }}
          placeholder="find a tag: “cinnamon sticks”, “Zimt”, “dry yeast”…"
          value={conceptDraft}
          onChange={setConceptDraft}
          suggestions={conceptSuggestions}
          onSelect={(s) => {
            setConceptId(s.key);
            setConceptLabel(s.title);
            setConceptDraft("");
            setConceptHint(null);
          }}
          onEnter={findConcept}
          disabled={conceptBusy}
        />
      </div>
      {conceptHint && <p className="sheet-sub" style={{ marginTop: 6, marginBottom: 0 }}>{conceptHint}</p>}

      <p className="sheet-sub">Unit</p>
      <div className="segmented" role="group" aria-label="Stock unit">
        {UNITS.map((u) => (
          <button key={u} className={unit === u ? "active" : ""} onClick={() => setUnit(u)}>
            {u}
          </button>
        ))}
      </div>

      <p className="sheet-sub">Tracking</p>
      <div className="segmented" role="group" aria-label="Tracking mode">
        <button className={binary ? "active" : ""} onClick={() => setBinary(true)}>
          Binary
        </button>
        <button className={binary ? "" : "active"} onClick={() => setBinary(false)}>
          Quantity
        </button>
      </div>
      <p className="sheet-sub">
        {binary
          ? "In stock / out of stock only. New stock starts present."
          : "Tracks a stock amount; recipes compare their exact amounts against it."}
      </p>

      {!binary && (
        <StepperRow
          label="Start with"
          hint="How much of it you have right now"
          value={stock}
          unit={unit}
          active
          onStep={(direction) => setStock(Math.max(0, round(stock + direction * step)))}
        />
      )}

      <StepperRow
        label="Package size"
        hint={binary ? undefined : "The size of one package — each scan adds or removes one of these"}
        value={packageSize}
        unit={unit}
        active
        min={step}
        onStep={(direction) => setPackageSize(Math.max(step, round(packageSize + direction * step)))}
      />

      <StepperRow
        label="Buy quantity"
        hint="How much you buy per purchase — the amount added to the shopping list"
        value={buyQty}
        unit={unit}
        active
        min={step}
        onStep={(direction) => setBuyQty(Math.max(step, round(buyQty + direction * step)))}
      />

      {!binary && (
        <StepperRow
          label="Alarm at"
          hint={alarmQty > 0 ? "Added automatically when stock falls to this" : "Disabled"}
          value={alarmQty}
          unit={unit}
          active={alarmQty > 0}
          onStep={(direction) => setAlarmQty(Math.max(0, round(alarmQty + direction * step)))}
        />
      )}

      <p className="sheet-sub">Barcode (optional)</p>
      <input
        className="import-input"
        style={{ fontFamily: "monospace" }}
        inputMode="numeric"
        placeholder="scan or type a product barcode…"
        value={barcode}
        onChange={(e) => setBarcode(e.target.value)}
      />

      {error && (
        <p className="sheet-sub" style={{ color: "var(--danger, #d33)" }}>⚠ {error}</p>
      )}

      <div className="sheet-actions">
        <button className="btn btn-ghost" onClick={onClose}>
          Cancel
        </button>
        <button className="btn btn-primary" disabled={busy || !name.trim()} onClick={submit}>
          {busy ? "Adding…" : "Add item"}
        </button>
      </div>
    </Sheet>
  );
}
