import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ControlCodeInfo, CustomLabelDesign, Item, LabelElement, LabelField } from "../types";
import { LABEL_FIELDS } from "../types";
import { fetchLabelPreviewUrl, fetchControlCustomLabel, fetchItemCustomLabel,
         saveControlCustomLabel, saveItemCustomLabel } from "../api";
import { TAPE_PRINTABLE, designHeightMm, elementText, fieldValues, newElementId, LABEL_PRESETS as PRESETS } from "../lib/labels";

export type LabelEditorTarget =
  | { kind: "item"; item: Item }
  | { kind: "control"; control: ControlCodeInfo };

interface LabelEditorProps {
  target: LabelEditorTarget;
  onClose: () => void;
  /** Fired after a successful save so lists/checkboxes can refresh. */
  onSaved: (target: LabelEditorTarget) => void;
}

const MM_TO_PX = 10; // canvas scale: 10 CSS px per mm
const PT_TO_MM = 0.352778;
const PT_TO_PX = PT_TO_MM * MM_TO_PX;

type Action = { type: "move" | "resize"; id: string } | null;

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/** Full-screen custom label editor in the LabelGenerator style: a white
 *  mm-grid canvas with draggable, resizable element boxes, snapping,
 *  per-element font sizes, presets (Gridfinity preset intentionally
 *  omitted), and a live backend-rendered print preview. The design is
 *  linked to exactly one item (or to one scanner control code). */
export default function LabelEditor({ target, onClose, onSaved }: LabelEditorProps) {
  const [design, setDesign] = useState<CustomLabelDesign | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewStale, setPreviewStale] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const actionRef = useRef<Action>(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const dragStartRef = useRef({ w: 0, h: 0, fontSizePt: 0 });
  const [snapLines, setSnapLines] = useState<{ x?: number; y?: number } | null>(null);

  const values = useMemo(() => fieldValues(target), [target]);
  const title = target.kind === "item" ? target.item.name : `${target.control.label} sticker`;

  // ---- load the existing design (item: saved; control: saved or default)
  useEffect(() => {
    let alive = true;
    setDesign(null);
    setSelectedId(null);
    const loaded = target.kind === "item"
      ? fetchItemCustomLabel(target.item.id)
      : fetchControlCustomLabel(target.control.key);
    loaded
      .then((d) => { if (alive) setDesign(d); })
      .catch(() => { if (alive) setNote("Could not load the saved design."); });
    return () => { alive = false; };
  }, [target]);

  // ---- live backend preview (debounced)
  useEffect(() => {
    if (!design) return;
    let alive = true;
    const timer = window.setTimeout(() => {
      fetchLabelPreviewUrl(
        target.kind === "item"
          ? { kind: "item", itemId: target.item.id }
          : { kind: "control", control: target.control.key },
        design
      )
        .then((url) => {
          if (!alive) return;
          setPreviewUrl((old) => {
            if (old) URL.revokeObjectURL(old);
            return url;
          });
        })
        .catch(() => { /* backend briefly away — keep the stale preview */ });
    }, 500);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [design, target, previewStale]);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const patchElement = useCallback((id: string, patch: Partial<LabelElement>) => {
    setDesign((prev) => prev && {
      ...prev,
      elements: prev.elements.map((el) => (el.id === id ? { ...el, ...patch } : el)),
    });
    setDirty(true);
  }, []);

  const updateDesign = useCallback((patch: Partial<CustomLabelDesign>) => {
    setDesign((prev) => prev && { ...prev, ...patch });
    setDirty(true);
  }, []);

  // ---- pointer interactions: move / resize with 0.5 mm snapping (mirror of
  // AnyLabel's LabelEditor pointer logic)
  useEffect(() => {
    const handleMove = (e: PointerEvent) => {
      const canvas = canvasRef.current;
      const current = actionRef.current;
      const active = design;
      if (!canvas || !current || !active) return;
      const rect = canvas.getBoundingClientRect();
      const scale = rect.width / (active.widthMm * MM_TO_PX);
      const toMmX = (px: number) => px / scale / MM_TO_PX;
      const toMmY = (px: number) => px / scale / MM_TO_PX;
      const heightMm = designHeightMm(active);
      const el = active.elements.find((i) => i.id === current.id);
      if (!el) return;

      if (current.type === "move") {
        let x = toMmX(e.clientX - rect.left - dragOffsetRef.current.x);
        let y = toMmY(e.clientY - rect.top - dragOffsetRef.current.y);
        const threshold = 0.5;
        let snapX: number | undefined;
        let snapY: number | undefined;
        // canvas center + edges
        if (Math.abs(x + el.w / 2 - active.widthMm / 2) < threshold) {
          x = active.widthMm / 2 - el.w / 2; snapX = active.widthMm / 2;
        }
        if (Math.abs(y + el.h / 2 - heightMm / 2) < threshold) {
          y = heightMm / 2 - el.h / 2; snapY = heightMm / 2;
        }
        for (const other of active.elements) {
          if (other.id === el.id) continue;
          if (Math.abs(x - other.x) < threshold) { x = other.x; snapX = other.x; }
          else if (Math.abs(x + el.w - (other.x + other.w)) < threshold) {
            x = other.x + other.w - el.w; snapX = other.x + other.w;
          } else if (Math.abs(x + el.w / 2 - (other.x + other.w / 2)) < threshold) {
            x = other.x + other.w / 2 - el.w / 2; snapX = other.x + other.w / 2;
          }
          if (Math.abs(y - other.y) < threshold) { y = other.y; snapY = other.y; }
          else if (Math.abs(y + el.h - (other.y + other.h)) < threshold) {
            y = other.y + other.h - el.h; snapY = other.y + other.h;
          } else if (Math.abs(y + el.h / 2 - (other.y + other.h / 2)) < threshold) {
            y = other.y + other.h / 2 - el.h / 2; snapY = other.y + other.h / 2;
          }
        }
        setSnapLines({ x: snapX, y: snapY });
        patchElement(el.id, {
          x: clamp(round2(x), 0, active.widthMm),
          y: clamp(round2(y), 0, 200),
        });
      } else if (current.type === "resize") {
        const w = Math.max(1, round2((toMmX(e.clientX - rect.left) - el.x) * 2) / 2);
        const h = Math.max(1, round2((toMmY(e.clientY - rect.top) - el.y) * 2) / 2);
        const startH = dragStartRef.current.h || el.h;
        const startFont = dragStartRef.current.fontSizePt;
        const ratio = startH > 0 ? h / startH : 1;
        const font = startFont > 0 ? clamp(Math.round(startFont * ratio * 10) / 10, 4, 300) : 0;
        patchElement(el.id, { w, h, fontSizePt: font });
      }
    };
    const handleUp = () => {
      actionRef.current = null;
      setSnapLines(null);
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleUp);
    };
  }, [design, patchElement]);

  const startMove = (e: React.PointerEvent, element: LabelElement) => {
    if (actionRef.current) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const scale = rect.width / ((design?.widthMm ?? 50) * MM_TO_PX);
    actionRef.current = { type: "move", id: element.id };
    dragOffsetRef.current = {
      x: (e.clientX - rect.left) - element.x * scale * MM_TO_PX,
      y: (e.clientY - rect.top) - element.y * scale * MM_TO_PX,
    };
    setSelectedId(element.id);
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  };

  const startResize = (e: React.PointerEvent, element: LabelElement) => {
    if (actionRef.current) return;
    actionRef.current = { type: "resize", id: element.id };
    dragStartRef.current = { w: element.w, h: element.h, fontSizePt: element.fontSizePt };
    setSelectedId(element.id);
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  };

  const addField = (field: LabelField) => {
    if (!design) return;
    const isGraphic = field === "qr" || field === "ean";
    const el: LabelElement = {
      id: newElementId(),
      field,
      x: round2(design.widthMm / 2 - (field === "qr" ? 5 : 7.5)),
      y: round2(designHeightMm(design) / 2 - (isGraphic ? 5 : 3)),
      w: field === "qr" ? 10 : 15,
      h: isGraphic ? 10 : 6,
      fontSizePt: isGraphic ? 0 : 14,
      text: field === "text" ? "Text" : "",
    };
    setDesign({ ...design, elements: [...design.elements, el] });
    setSelectedId(el.id);
    setDirty(true);
  };

  const removeSelected = () => {
    if (!design || !selectedId) return;
    setDesign({ ...design, elements: design.elements.filter((el) => el.id !== selectedId) });
    setSelectedId(null);
    setDirty(true);
  };

  const save = async () => {
    if (!design || saving) return;
    setSaving(true);
    setNote(null);
    try {
      if (target.kind === "item") {
        await saveItemCustomLabel(target.item.id, design);
      } else {
        await saveControlCustomLabel(target.control.key, design);
      }
      setDirty(false);
      setPreviewStale((n) => n + 1);
      onSaved(target);
    } catch {
      setNote("Saving failed — is the backend reachable?");
    } finally {
      setSaving(false);
    }
  };

  const close = () => {
    if (dirty && !window.confirm("Close without saving? Your changes are lost.")) return;
    onClose();
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { close(); return; }
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(
        (document.activeElement?.tagName ?? ""));
      if (typing) return;
      if ((e.key === "Delete" || e.key === "Backspace") && selectedId) {
        e.preventDefault();
        removeSelected();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  const selected = design?.elements.find((el) => el.id === selectedId) ?? null;
  const heightMm = design ? designHeightMm(design) : 18.1;

  if (!design) {
    return (
      <div className="label-editor-overlay">
        <div className="label-editor-loading">Loading label…</div>
      </div>
    );
  }

  return (
    <div className="label-editor-overlay" role="dialog" aria-label={`Edit label: ${title}`}>
      <header className="label-editor-header">
        <div>
          <h2 className="sheet-title">Edit label — {title}</h2>
          <p className="sheet-sub">
            {target.kind === "control"
              ? "Scanner sticker design. The code digits stay fixed so the wedge keeps working."
              : "This design belongs to this item only."}
          </p>
        </div>
        <div className="sheet-actions">
          <button className="btn btn-ghost" onClick={close}>Close</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : dirty ? "Save label" : "Saved"}
          </button>
        </div>
      </header>

      {note && <p className="sheet-sub label-editor-note">{note}</p>}

      <div className="label-editor-body">
        <aside className="label-editor-side">
          <h3 className="sheet-title" style={{ fontSize: 15 }}>Presets</h3>
          <div className="label-toolbox">
            {PRESETS.map((preset) => (
              <button
                key={preset.id}
                className="chip"
                title={`Replace the layout with the preset (${preset.design.tape} mm tape)`}
                onClick={() => {
                  if (design.elements.length > 0 && !window.confirm(
                    `Replace the current layout with the "${preset.label}" preset?`)) return;
                  setDesign({
                    tape: preset.design.tape,
                    widthMm: preset.design.widthMm,
                    elements: preset.design.elements.map((el) => ({ ...el })),
                  });
                  setSelectedId(null);
                  setDirty(true);
                }}
              >
                {preset.label}
              </button>
            ))}
          </div>

          <h3 className="sheet-title" style={{ fontSize: 15 }}>Layout</h3>
          <div className="field-row">
            <label className="field-label">Label width (mm)</label>
            <input
              className="field-input"
              type="number" min={10} max={300} step={1}
              value={Math.round(design.widthMm)}
              onChange={(e) => updateDesign({ widthMm: clamp(parseFloat(e.target.value) || 50, 10, 300) })}
            />
          </div>
          <div className="field-row">
            <label className="field-label">Tape</label>
            <div className="segmented" role="group">
              {[12, 24].map((tape) => (
                <button
                  key={tape}
                  className={design.tape === tape ? "active" : ""}
                  onClick={() => {
                    const elements = design.elements.map((el) => {
                      // keep boxes inside the new printable strip
                      const maxY = TAPE_PRINTABLE[tape as 12 | 24] - el.h;
                      return { ...el, y: clamp(round2(el.y), 0, Math.max(0, maxY)) };
                    });
                    updateDesign({ tape: tape as 12 | 24, elements });
                  }}
                >
                  {tape} mm
                </button>
              ))}
            </div>
          </div>

          <h3 className="sheet-title" style={{ fontSize: 15 }}>Add element</h3>
          <div className="label-toolbox">
            {LABEL_FIELDS.map((field) => (
              <button
                key={field.id}
                className="chip"
                title={field.hint}
                onClick={() => addField(field.id)}
              >
                + {field.label}
              </button>
            ))}
          </div>

          {selected ? (
            <>
              <h3 className="sheet-title" style={{ fontSize: 15 }}>Element</h3>
              <div className="label-inspector">
                <span className="segmented" style={{ display: "inline-block", marginBottom: 8 }}>
                  <button className="active" style={{ pointerEvents: "none" }}>
                    {LABEL_FIELDS.find((f) => f.id === selected.field)?.label ?? selected.field}
                  </button>
                </span>
                {selected.field === "text" && (
                  <div className="field-row">
                    <label className="field-label">Text</label>
                    <input
                      className="field-input"
                      type="text"
                      value={selected.text ?? ""}
                      onChange={(e) => patchElement(selected.id, { text: e.target.value })}
                    />
                  </div>
                )}
                {selected.field !== "qr" && selected.field !== "ean" && (
                  <div className="field-row">
                    <label className="field-label">Font (pt)</label>
                    <input
                      className="field-input"
                      type="number" min={4} max={100} step={0.5}
                      value={selected.fontSizePt}
                      onChange={(e) => patchElement(selected.id, {
                        fontSizePt: clamp(parseFloat(e.target.value) || 10, 4, 100),
                      })}
                    />
                  </div>
                )}
                <div className="label-inspector-grid">
                  {(["x", "y", "w", "h"] as const).map((key) => (
                    <div className="field-row" key={key}>
                      <label className="field-label">{key.toUpperCase()} (mm)</label>
                      <input
                        className="field-input"
                        type="number" step={0.5}
                        value={selected[key]}
                        onChange={(e) =>
                          patchElement(selected.id, { [key]: parseFloat(e.target.value) || 0 } as Partial<LabelElement>)}
                      />
                    </div>
                  ))}
                </div>
                <button className="btn btn-danger btn-block" onClick={removeSelected}>
                  Remove element
                </button>
              </div>
            </>
          ) : (
            <p className="sheet-sub">
              Tap an element on the canvas to select it. Drag to move, drag the
              corner dot to resize (the font scales with the height).
            </p>
          )}
        </aside>

        <div className="label-editor-main">
          <div className="label-preview-block">
            <h3 className="sheet-title" style={{ fontSize: 15 }}>Canvas</h3>
            <div className="label-scroll">
              <div
                ref={canvasRef}
                className="label-canvas"
                style={{ width: design.widthMm * MM_TO_PX, height: heightMm * MM_TO_PX }}
                onPointerDown={() => setSelectedId(null)}
              >
                {design.elements.map((element) => {
                  const text = elementText(element, values);
                  return (
                    <div
                      key={element.id}
                      className={`label-element${selectedId === element.id ? " selected" : ""}`}
                      style={{
                        left: element.x * MM_TO_PX,
                        top: element.y * MM_TO_PX,
                        width: element.w * MM_TO_PX,
                        height: element.h * MM_TO_PX,
                        fontSize: Math.max(4, element.fontSizePt) * PT_TO_PX,
                      }}
                      onPointerDown={(e) => {
                        e.stopPropagation();
                        startMove(e, element);
                      }}
                    >
                      {element.field === "qr" ? (
                        <span className="label-qr-ph">QR</span>
                      ) : element.field === "ean" ? (
                        <span className="label-ean-ph" aria-hidden />
                      ) : (
                        <span className="label-element-text">{text || "·"}</span>
                      )}
                      {selectedId === element.id && (
                        <span
                          className="label-resize-handle"
                          onPointerDown={(e) => startResize(e, element)}
                        />
                      )}
                    </div>
                  );
                })}
                {snapLines?.x !== undefined && (
                  <span className="label-snapline" style={{ left: snapLines.x * MM_TO_PX }} />
                )}
                {snapLines?.y !== undefined && (
                  <span className="label-snapline horizontal" style={{ top: snapLines.y * MM_TO_PX }} />
                )}
              </div>
            </div>
            <p className="sheet-sub">
              {design.widthMm} × {heightMm.toFixed(1)} mm on {design.tape} mm tape
              {" — "}dashed lines are element boxes, the print preview shows the real label.
            </p>
          </div>

          <div className="label-preview-block">
            <h3 className="sheet-title" style={{ fontSize: 15 }}>Print preview</h3>
            {previewUrl ? (
              <img
                className="label-preview-img"
                src={previewUrl}
                alt={`Print preview of the ${title} label`}
              />
            ) : (
              <div className="label-preview-img label-preview-pending">Rendering…</div>
            )}
          </div>
        </div>
      </div>

    </div>
  );
}
