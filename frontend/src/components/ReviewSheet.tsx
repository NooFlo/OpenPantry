import { useState } from "react";
import type { PendingBarcode } from "../types";
import Sheet from "./Sheet";
import { IconBarcode, IconCheck, IconPlus } from "./Icons";

interface ReviewSheetProps {
  entries: PendingBarcode[];
  /** Assign a pending barcode to an existing item (or a fresh name — the
   *  server derives package size/unit from the Open Food Facts product). */
  onAssign: (barcode: string, target: { itemId?: string; itemName?: string }) => Promise<void>;
  /** Remove the queue entry for good (vanishes on every device). */
  onRemove: (barcode: string) => void;
  onClose: () => void;
}

function EntryCard({ entry, onAssign, onRemove }: {
  entry: PendingBarcode;
  onAssign: ReviewSheetProps["onAssign"];
  onRemove: ReviewSheetProps["onRemove"];
}) {
  const [busy, setBusy] = useState(false);
  const [itemName, setItemName] = useState(entry.name);
  const [error, setError] = useState<string | null>(null);

  const assign = async (target: { itemId?: string; itemName?: string }) => {
    setBusy(true);
    setError(null);
    try {
      await onAssign(entry.barcode, target);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 14, padding: 14, marginBottom: 12 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        {entry.imageUrl && (
          <img
            src={entry.imageUrl}
            alt=""
            style={{ width: 56, height: 56, objectFit: "contain", borderRadius: 8, background: "#fff" }}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        )}
        <div style={{ flex: 1 }}>
          <strong>{entry.name}</strong>
          {entry.brand && <div className="item-sub">{entry.brand}</div>}
          <div className="item-sub" style={{ fontFamily: "monospace" }}>
            {entry.barcode}{entry.quantity ? ` · ${entry.quantity}` : ""}
          </div>
        </div>
        <button className="icon-btn" title="Remove from the review queue" aria-label="Remove" onClick={() => onRemove(entry.barcode)}>
          ✕
        </button>
      </div>

      {entry.suggestions.length > 0 && (
        <>
          <p className="sheet-sub" style={{ margin: "10px 0 6px" }}>Maybe it's one of these:</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {entry.suggestions.map((s) => (
              <button key={s.id} className="btn btn-ghost" disabled={busy} onClick={() => assign({ itemId: s.id })}>
                <IconCheck size={14} /> {s.name}
              </button>
            ))}
          </div>
        </>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12 }}>
        <input
          className="import-input"
          style={{ marginBottom: 0 }}
          placeholder="new item name…"
          value={itemName}
          disabled={busy}
          onChange={(e) => setItemName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && itemName.trim()) assign({ itemName: itemName.trim() });
          }}
        />
        <button
          className="icon-btn"
          aria-label="Create new item with this barcode"
          title="Create a new item with this barcode"
          disabled={busy || !itemName.trim()}
          onClick={() => assign({ itemName: itemName.trim() })}
        >
          <IconPlus size={18} />
        </button>
      </div>
      <p className="item-sub" style={{ margin: "6px 0 0" }}>
        Package size and unit come from the product data{error ? ` — ${error}` : ""} when creating a new item.
      </p>
    </div>
  );
}

/** Live review popup for scanned barcodes without an inventory mapping:
 *  Open Food Facts data and generic-catalog suggestions, confirmed in place. */
export default function ReviewSheet({ entries, onAssign, onRemove, onClose }: ReviewSheetProps) {
  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title"><IconBarcode size={18} /> Scanned without a mapping</h2>
      <p className="sheet-sub">
        {entries.length} scanned barcode{entries.length === 1 ? "" : "s"} {entries.length === 1 ? "is" : "are"} not
        linked to an item yet — pick a matching item, or create a new one. Assigned once, it deducts and restocks
        from then on.
      </p>
      {entries.map((entry) => (
        <EntryCard key={entry.barcode} entry={entry} onAssign={onAssign} onRemove={onRemove} />
      ))}
      <div className="sheet-actions">
        <button className="btn btn-ghost" onClick={onClose}>
          {entries.length > 0 ? "Later" : "Done"}
        </button>
      </div>
    </Sheet>
  );
}
