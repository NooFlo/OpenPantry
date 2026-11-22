import { useEffect, useMemo, useState } from "react";
import type { ControlCodeInfo, CustomLabelInfo, Item } from "../types";
import { fetchControlCodes } from "../api";
import { IconPencil, IconTag } from "./Icons";

interface BarcodesViewProps {
  items: Item[];
  /** Items with a custom label, most recently added first (backend order). */
  customLabels: CustomLabelInfo[];
  onEditItemLabel: (item: Item) => void;
  onEditControlLabel: (control: ControlCodeInfo) => void;
}

function download(url: string) {
  window.location.assign(url);
}

function formatDate(value: string): string {
  const date = new Date(value.replace(" ", "T") + "Z");
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** Full-page "Labels & barcodes" view: the two scanner control codes with
 *  their (editable) sticker designs and printable exports, plus all items
 *  carrying a custom label — most recently added first, with checkboxes
 *  for batch printing an Epson .lemd strip. Replaces the old bottom-sheet
 *  labels submenu; with custom labels, item labels are strictly opt-in
 *  per item (the fixed QR+name template and its any-item picker are gone). */
export default function BarcodesView({ items, customLabels, onEditItemLabel,
                                       onEditControlLabel }: BarcodesViewProps) {
  const [codes, setCodes] = useState<ControlCodeInfo[]>([]);
  const [tape, setTape] = useState<12 | 24>(24);
  const [stickerFormat, setStickerFormat] = useState<"ean" | "qr">("ean");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchControlCodes().then(setCodes).catch(() => { /* backend away */ });
  }, []);

  const rows = useMemo(() => customLabels
    .map((info) => ({ info, item: items.find((i) => i.id === info.itemId) ?? null }))
    .filter((row) => row.item !== null) as { info: CustomLabelInfo; item: Item }[],
    [customLabels, items]);

  const pickedIds = [...picked].filter((id) => rows.some((r) => r.item.id === id));

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div>
      <section className="barcodes-section">
        <h2 className="sheet-title" style={{ fontSize: 18 }}>Scanner control codes</h2>
        <p className="sheet-sub">
          Two stickers for the USB scanner: BOUGHT switches to restocking, TRASH
          switches back to the default — every scan deducts one package. Their
          designs are editable like item labels; the code digits stay fixed so
          the Rock5 scanner bridge keeps working.
        </p>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", margin: "10px 0 14px" }}>
          <div className="segmented" role="group" aria-label="Tape width">
            <button className={tape === 12 ? "active" : ""} onClick={() => setTape(12)}>12 mm</button>
            <button className={tape === 24 ? "active" : ""} onClick={() => setTape(24)}>24 mm</button>
          </div>
          <div className="segmented" role="group" aria-label="Sticker code type">
            <button className={stickerFormat === "ean" ? "active" : ""}
                    onClick={() => setStickerFormat("ean")}>EAN (1D scanner)</button>
            <button className={stickerFormat === "qr" ? "active" : ""}
                    onClick={() => setStickerFormat("qr")}>QR (2D scanner)</button>
          </div>
        </div>

        {codes.map((code) => (
          <div key={code.key} className="control-code-card">
            <img
              className="control-code-thumb"
              src={`/api/labels/custom/control/${code.key}/png`}
              alt={`${code.label} sticker`}
            />
            <div style={{ flex: 1, minWidth: 180 }}>
              <div className="item-name">{code.label}</div>
              <div className="item-sub" style={{ fontFamily: "monospace" }}>{code.code}</div>
              <div className="item-sub">{code.hint}</div>
            </div>
            <button className="btn btn-ghost" onClick={() => onEditControlLabel(code)}>
              <IconPencil size={15} />
              Edit label
            </button>
          </div>
        ))}

        <div className="sheet-actions">
          <button className="btn btn-ghost" onClick={() => window.open("/print/control-codes", "_blank")}>
            Print sheet (A4)
          </button>
          <button
            className="btn btn-primary"
            onClick={() => download(`/api/labels/control-codes.lemd?tape=${tape}&format=${stickerFormat}`)}
          >
            Epson strip (.lemd)
          </button>
        </div>
      </section>

      <section className="barcodes-section">
        <h2 className="sheet-title" style={{ fontSize: 18 }}>Custom item labels</h2>
        <p className="sheet-sub">
          Every item with a &quot;Create custom label&quot; design, most recently
          added first. Pick the ones to print and export an Epson strip — or
          edit a design below.
        </p>

        {rows.length === 0 ? (
          <div className="empty-state">
            No custom labels yet — open an item, check &quot;Create custom
            label&quot; and design its label.
          </div>
        ) : (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              <button className="btn btn-ghost" onClick={() => setPicked(new Set(rows.map((r) => r.item.id)))}>
                Select all ({rows.length})
              </button>
              <button className="btn btn-ghost" onClick={() => setPicked(new Set())}>
                Clear
              </button>
            </div>

            {rows.map(({ info, item }) => (
              <div key={item.id} className="list-row-wrap">
                <button
                  className="list-row"
                  style={{ display: "flex", width: "100%", alignItems: "center", gap: 10 }}
                  onClick={() => toggle(item.id)}
                  aria-pressed={picked.has(item.id)}
                >
                  <span aria-hidden style={{
                    width: 22, height: 22, borderRadius: 6, flexShrink: 0,
                    border: "1.5px solid var(--border)",
                    background: picked.has(item.id) ? "var(--accent)" : "transparent",
                    display: "grid", placeItems: "center",
                  }}>
                    {picked.has(item.id) && "✓"}
                  </span>
                  <img
                    src={`/api/labels/custom/item/${item.id}/png`}
                    alt=""
                    style={{ height: 34, width: "auto", borderRadius: 3, background: "#fff", flexShrink: 0 }}
                  />
                  <div className="info" style={{ flex: 1, textAlign: "left" }}>
                    <div className="item-name">{item.name}</div>
                    <div className="item-sub">
                      {item.category} · designed {formatDate(info.createdAt)}
                    </div>
                  </div>
                </button>
                <div className="row-stepper">
                  <button className="icon-btn" aria-label={`Edit ${item.name} label`}
                          title="Edit label" onClick={() => onEditItemLabel(item)}>
                    <IconTag size={16} />
                  </button>
                </div>
              </div>
            ))}

            <div className="sheet-actions" style={{ marginTop: 12 }}>
              <button
                className="btn btn-primary"
                disabled={pickedIds.length === 0}
                onClick={() => download(`/api/labels/custom.lemd?ids=${pickedIds.join(",")}&tape=${tape}`)}
              >
                <IconTag size={16} />
                Epson strip: {pickedIds.length || "no"} label{pickedIds.length === 1 ? "" : "s"} ({tape} mm)
              </button>
            </div>
            <p className="sheet-sub">
              The .lemd download opens in the Epson Label Editor app and prints
              over Bluetooth. Each label prints from its own saved design.
            </p>
          </>
        )}
      </section>
    </div>
  );
}
