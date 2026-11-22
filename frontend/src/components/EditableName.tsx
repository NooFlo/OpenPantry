import { useEffect, useRef, useState } from "react";
import { IconPencil } from "./Icons";

interface EditableNameProps {
  name: string;
  /** Commit a rename; reject to show the error inline. */
  onRename: (name: string) => Promise<void>;
}

/** Click-to-rename: pencil next to the name swaps in an inline input.
 *  Enter saves, Escape/cancel discards, empty or unchanged names do
 *  nothing, a rejected rename shows the reason (e.g. name taken). */
export default function EditableName({ name, onRename }: EditableNameProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (name !== draft) setDraft(name);
    setEditing(false);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const stop = () => {
    setDraft(name);
    setEditing(false);
    setError(null);
  };

  const commit = async () => {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === name) {
      stop();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onRename(trimmed);
      setEditing(false);
    } catch (requestError) {
      setError(String((requestError as Error).message ?? requestError));
      inputRef.current?.focus();
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <span style={{ display: "block" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            ref={inputRef}
            className="import-input"
            style={{ marginBottom: 0, minWidth: 200 }}
            value={draft}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit();
              else if (e.key === "Escape") stop();
            }}
          />
          <button className="btn btn-primary btn-sm" disabled={busy || !draft.trim()} onClick={commit}>
            {busy ? "Saving…" : "Save"}
          </button>
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={stop}>
            Cancel
          </button>
        </div>
        {error && <p className="sheet-sub" style={{ marginTop: 6, marginBottom: 0 }}>⚠ {error}</p>}
      </span>
    );
  }

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      {name}
      <button
        className="icon-btn"
        style={{ padding: "4px 7px" }}
        aria-label="Rename item"
        title="Rename this item"
        onClick={() => setEditing(true)}
      >
        <IconPencil size={15} />
      </button>
    </span>
  );
}
