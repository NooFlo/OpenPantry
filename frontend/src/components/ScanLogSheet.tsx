import type { ScanLogEntry } from "../types";
import Sheet from "./Sheet";
import { IconPlus, IconMinus, IconBarcode } from "./Icons";

function describe(entry: ScanLogEntry): { verb: string; tone: "add" | "remove" | "unknown" } {
  if (entry.kind.startsWith("unknown"))
    return { verb: "Missing info — not linked to any item", tone: "unknown" };
  if (entry.kind === "bought") return { verb: "Added 1 package", tone: "add" };
  if (entry.kind === "empty") return { verb: "Emptied", tone: "remove" };
  return { verb: "Removed 1 package", tone: "remove" };
}

/** "Did my scans arrive?" — the live scanner history, newest first. */
export default function ScanLogSheet({ scans, onOpenReview, onClose }: {
  scans: ScanLogEntry[];
  onOpenReview: () => void;
  onClose: () => void;
}) {
  const unknown = scans.filter((e) => e.kind.startsWith("unknown"));
  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title"><IconBarcode size={18} /> Recent scans</h2>
      <p className="sheet-sub">
        Every scan from the USB scanner — live, newest first.
        {unknown.length > 0 && ` ${unknown.length} scan${unknown.length === 1 ? "" : "s"} still missing information.`}
      </p>

      {scans.length === 0 && (
        <div className="empty-state">Nothing scanned yet.</div>
      )}

      {scans.map((entry) => {
        const { verb, tone } = describe(entry);
        const time = (entry.at || "").slice(11, 16);
        const day = (entry.at || "").slice(5, 10);
        return (
          <div key={entry.id} style={{
            display: "flex", gap: 12, alignItems: "center",
            padding: "10px 0", borderBottom: "1px solid var(--border)",
          }}>
            <span aria-hidden style={{ flexShrink: 0, color: tone === "add" ? "var(--ok, #2f9e44)" : tone === "remove" ? "var(--danger, #e03131)" : "var(--warn, #e8590c)" }}>
              {tone === "add" ? <IconPlus size={18} /> : tone === "remove" ? <IconMinus size={18} /> : <IconBarcode size={18} />}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="item-name" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {entry.itemName ?? "Unknown product"}
              </div>
              <div className="item-sub">{verb}</div>
              {tone === "unknown" && entry.barcode && (
                <div className="item-sub" style={{ fontFamily: "monospace" }}>{entry.barcode}</div>
              )}
            </div>
            <span className="item-sub" style={{ textAlign: "right", flexShrink: 0 }}>
              {day} · {time}
            </span>
          </div>
        );
      })}

      <div className="sheet-actions">
        {unknown.length > 0 && (
          <button
            className="btn btn-primary"
            onClick={() => { onOpenReview(); onClose(); }}
          >
            <IconBarcode size={16} />
            Resolve missing scans
          </button>
        )}
        <button className="btn btn-ghost" onClick={onClose}>Done</button>
      </div>
    </Sheet>
  );
}
