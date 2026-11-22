import { useEffect, useMemo, useState } from "react";
import type { Item, ItemCreatePayload, MissingGroup } from "../types";
import { fetchMissingGroups } from "../api";
import AddItemSheet from "./AddItemSheet";
import Autocomplete from "./Autocomplete";
import Sheet from "./Sheet";
import { formatStock } from "../lib/tracking";

interface MissingItemsSheetProps {
  items: Item[];
  /** Categories already in use — autocomplete suggestions in the item sheet. */
  categories: string[];
  /** Merge one missing-food group onto an existing inventory item. */
  onMerge: (key: string, itemId: string) => Promise<void>;
  /** Create a new inventory item and merge the group onto it. */
  onCreateAndMerge: (key: string, payload: ItemCreatePayload) => Promise<void>;
  onClose: () => void;
}

/** Settings > Missing items: every ingredient recipes reference that the
 *  pantry cannot account for, grouped by food and sorted by how many
 *  recipes use it. Merge relinks + renames the rows onto one item;
 *  create adds a new item and links it in one go. */
export default function MissingItemsSheet({ items, categories, onMerge, onCreateAndMerge, onClose }: MissingItemsSheetProps) {
  const [groups, setGroups] = useState<MissingGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<MissingGroup | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = () => {
    setError(null);
    fetchMissingGroups()
      .then((all) => {
        setGroups(all);
        // the selected group may have vanished (merged elsewhere): drop selection
        setSelected((prev) => (prev && all.some((g) => g.key === prev.key) ? prev : null));
      })
      .catch((e) => setError(String((e as Error).message ?? e)));
  };

  useEffect(reload, []);

  const itemSuggestions = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items
      .filter((item) => !q || item.name.toLowerCase().includes(q))
      .slice(0, 8)
      .map((item) => ({ key: item.id, title: item.name, hint: `${item.category} · ${formatStock(item)}` }));
  }, [items, query]);

  const merge = async (itemId: string) => {
    if (!selected || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onMerge(selected.key, itemId);
      const item = items.find((i) => i.id === itemId);
      setNotice(`Merged into ${item?.name ?? "the item"} — ${selected.recipes.length > 1 ? `${selected.recipes.length} recipes use it now` : "the recipe uses it now"}.`);
      setSelected(null);
      setQuery("");
      reload();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const createAndMerge = async (payload: ItemCreatePayload) => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      await onCreateAndMerge(selected.key, payload);
      setNotice(`Created ${payload.name} and linked ${selected.recipes.length > 1 ? `${selected.recipes.length} recipes` : "the recipe"} to it.`);
      setSelected(null);
      setCreateOpen(false);
      reload();
    } finally {
      setBusy(false);
    }
  };

  const recipesLine = (g: MissingGroup) =>
    g.recipeCount === 1 ? "1 recipe" : `${g.recipeCount} recipes`;

  return (
    <Sheet onClose={onClose}>
      {selected == null ? (
        <>
          <h2 className="sheet-title">Missing items</h2>
          <p className="sheet-sub">
            Ingredients your recipes use that are not matched to any inventory item. Sorted by how often they appear.
          </p>
          {notice && <p className="sheet-sub" style={{ color: "var(--accent)" }}>{notice}</p>}
          {error && <p className="sheet-sub" style={{ color: "#d33" }}>{error}</p>}
          {groups == null && !error && <p className="sheet-sub">Loading…</p>}
          {groups != null && groups.length === 0 && !error && (
            <p className="sheet-sub">Nothing missing — every tracked ingredient is matched to the pantry.</p>
          )}
          <div className="missing-group-list">
            {(groups ?? []).map((g) => (
              <button
                key={g.key}
                className="missing-group-row"
                onClick={() => {
                  setSelected(g);
                  setQuery("");
                  setNotice(null);
                  setError(null);
                }}
              >
                <span className="missing-group-main">
                  <span className="missing-group-name">{g.name}</span>
                  {g.conceptLabel && g.conceptLabel.toLowerCase() !== g.name.toLowerCase() && (
                    <span className="missing-group-alias">aka {g.conceptLabel}</span>
                  )}
                  <span className="missing-group-recipes">
                    {recipesLine(g)}
                    {g.rowCount > g.recipeCount ? ` · ${g.rowCount} mentions` : ""}
                  </span>
                </span>
                <span className="missing-group-arrow">›</span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <>
          <button
            className="icon-btn"
            aria-label="Back to all missing items"
            onClick={() => {
              setSelected(null);
              setQuery("");
              setError(null);
            }}
          >
            ‹
          </button>
          <h2 className="sheet-title">{selected.name}</h2>
          <p className="sheet-sub">
            Raw lines like “{selected.sampleRaw}” — used in {recipesLine(selected).toLowerCase()}:
          </p>
          <div className="chip-row" style={{ flexWrap: "wrap", margin: "6px 0 14px" }}>
            {selected.recipes.map((r) => (
              <span key={r.id} className="tag-chip">{r.title}</span>
            ))}
          </div>

          <p className="sheet-sub">Merge with an item in your inventory</p>
          <Autocomplete
            className="import-input"
            placeholder="Search inventory items…"
            value={query}
            onChange={setQuery}
            suggestions={itemSuggestions}
            onSelect={(s) => merge(s.key)}
          />
          {error && <p className="sheet-sub" style={{ color: "#d33", marginTop: 6 }}>{error}</p>}
          {busy && <p className="sheet-sub" style={{ marginTop: 6 }}>Merging…</p>}

          <p className="sheet-sub" style={{ marginTop: 18 }}>Or add it as a new inventory item</p>
          <button className="btn btn-ghost" onClick={() => setCreateOpen(true)} disabled={busy}>
            Create item “{selected.name}”
          </button>
          <p className="sheet-sub" style={{ marginTop: 6 }}>
            Creates the item with everything you set (stock, tag, category) and links the recipes to it right away.
          </p>
        </>
      )}

      {createOpen && selected && (
        <AddItemSheet
          onAddItem={createAndMerge}
          onClose={() => setCreateOpen(false)}
          categories={categories}
          initialName={selected.name}
          initialConcept={selected.conceptId && selected.conceptLabel ? { id: selected.conceptId, label: selected.conceptLabel } : null}
        />
      )}
    </Sheet>
  );
}
