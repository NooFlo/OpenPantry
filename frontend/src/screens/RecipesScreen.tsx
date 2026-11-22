import { Fragment, useMemo, useState } from "react";
import { CANONICAL_CATEGORIES } from "../types";
import type { Ingredient, Item, ItemCreatePayload, ModelList, Recipe, RecipeEditPatch, Settings, SettingsPatch } from "../types";
import { importRecipe } from "../api";
import { maxPortions, missingAmount, scaledAmount, ingredientInStock, formatQty, stepSegments, baseIngredientName } from "../lib/cooking";
import { isBinary } from "../lib/tracking";
import { RECIPE_FILTERS, formatMinutes } from "../lib/tags";
import { useMediaQuery } from "../lib/useMediaQuery";
import Sheet from "../components/Sheet";
import ThemeToggle from "../components/ThemeToggle";
import ModelSettingsSheet from "../components/ModelSettingsSheet";
import MissingItemsSheet from "../components/MissingItemsSheet";
import {
  IconCheck,
  IconClock,
  IconGear,
  IconMinus,
  IconPencil,
  IconPlus,
  IconSearch,
  IconX,
} from "../components/Icons";

type Sort = "newest" | "quickest" | "az";

const SORTS: { id: Sort; label: string }[] = [
  { id: "newest", label: "Newest" },
  { id: "quickest", label: "Quickest" },
  { id: "az", label: "A–Z" },
];

interface RecipesScreenProps {
  recipes: Recipe[];
  items: Item[];
  portions: number;
  onPortionsChange: (p: number) => void;
  onImport: (recipe: Recipe) => void;
  onAddMissing: (recipe: Recipe) => Promise<void>;
  onMatchIngredient: (recipeId: string, ingredientId: string, itemName: string) => void;
  onSelectIngredient: (recipeId: string, ingredientId: string) => void;
  onSaveRecipeEdit: (recipeId: string, patch: RecipeEditPatch) => Promise<unknown>;
  onDeleteRecipe: (recipeId: string) => Promise<unknown>;
  /** Settings > Missing items: merge a group of unmatched rows onto one item. */
  onMergeMissing: (key: string, itemId: string) => Promise<void>;
  /** Settings > Missing items: create the item for a group and link it. */
  onCreateMissingItem: (key: string, payload: ItemCreatePayload) => Promise<void>;
  settings: Settings;
  models: ModelList;
  onSaveSettings: (patch: SettingsPatch) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

/** Draft of a recipe being edited: plain text everything, sent to the API. */
interface RecipeDraft {
  title: string;
  source: string;
  basePortions: number;
  ingredients: { id?: string; raw: string }[];
  steps: string[];
}

export default function RecipesScreen({
  recipes,
  items,
  portions,
  onPortionsChange,
  onImport,
  onAddMissing,
  onMatchIngredient,
  onSelectIngredient,
  onSaveRecipeEdit,
  onDeleteRecipe,
  onMergeMissing,
  onCreateMissingItem,
  settings,
  models,
  onSaveSettings,
  theme,
  onToggleTheme,
}: RecipesScreenProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false);
  const [missingOpen, setMissingOpen] = useState(false);
  const [kind, setKind] = useState<"link" | "text">("link");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [activeFilters, setActiveFilters] = useState<string[]>([]);
  const [sort, setSort] = useState<Sort>("newest");
  const [addingId, setAddingId] = useState<string | null>(null);
  const [addedId, setAddedId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<"ingredients" | "recipe">("ingredients");
  const [activeStep, setActiveStep] = useState<number | null>(null);
  const [editState, setEditState] = useState<{ recipeId: string; draft: RecipeDraft } | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);

  // categories in use — autocomplete suggestions for the nested item sheet
  const categories = useMemo(() => [...new Set(items.map((i) => i.category))], [items]);
  // canonical order first, then customs alphabetically — picker suggestions
  const categorySuggestions = useMemo(
    () => [
      ...CANONICAL_CATEGORIES.filter((c) => categories.includes(c)),
      ...categories.filter((c) => !CANONICAL_CATEGORIES.includes(c)).sort(),
    ],
    [categories]
  );

  const selected = recipes.find((r) => r.id === selectedId) ?? null;
  const twoPane = useMediaQuery("(min-width: 1180px)");

  const filterChips = useMemo(() => {
    const canonical = new Set(RECIPE_FILTERS.map((f) => f.toLowerCase()));
    const display = new Map<string, string>();
    const counts = new Map<string, number>();
    for (const recipe of recipes) {
      for (const tag of recipe.tags ?? []) {
        if (!tag.trim()) continue;
        const key = tag.toLowerCase();
        if (!canonical.has(key) || !display.has(key)) display.set(key, tag);
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
    }
    const canonicalChips = RECIPE_FILTERS.filter((f) => counts.has(f.toLowerCase()));
    const extraChips = [...counts.entries()]
      .filter(([key]) => !canonical.has(key))
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([key]) => display.get(key)!);
    return [...canonicalChips, ...extraChips];
  }, [recipes]);

  const filteredRecipes = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = recipes.filter((recipe) => {
      if (activeFilters.length > 0) {
        const tags = (recipe.tags ?? []).map((t) => t.toLowerCase());
        if (!activeFilters.every((f) => tags.includes(f.toLowerCase()))) return false;
      }
      if (!q) return true;
      const haystack = [recipe.title, recipe.cuisine, recipe.category, ...(recipe.tags ?? [])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
    const byName = (a: Recipe, b: Recipe) => a.title.localeCompare(b.title);
    if (sort === "az") return [...filtered].sort(byName);
    if (sort === "quickest")
      return [...filtered].sort(
        (a, b) => (a.totalMinutes ?? Infinity) - (b.totalMinutes ?? Infinity) || byName(a, b)
      );
    // recipes arrive newest-first from the API; keep that order for ties
    return filtered;
  }, [recipes, query, activeFilters, sort]);

  const doImport = async () => {
    if (!value.trim() || busy) return;
    setBusy(true);
    const recipe = await importRecipe(kind, value.trim());
    setBusy(false);
    setImportOpen(false);
    setValue("");
    onImport(recipe);
    setSelectedId(recipe.id);
  };

  const toggleFilter = (filter: string) => {
    setActiveFilters((prev) =>
      prev.includes(filter) ? prev.filter((f) => f !== filter) : [...prev, filter]
    );
  };

  const doAddMissing = async (recipe: Recipe) => {
    if (addingId === recipe.id || addedId === recipe.id) return;
    setAddingId(recipe.id);
    try {
      await onAddMissing(recipe);
      setAddedId(recipe.id);
      window.setTimeout(() => setAddedId((id) => (id === recipe.id ? null : id)), 2000);
    } catch (err) {
      console.error(err);
    } finally {
      setAddingId(null);
    }
  };

  const editingDraft =
    editState && selected && editState.recipeId === selected.id ? editState.draft : null;
  const setDraft = (updater: (d: RecipeDraft) => RecipeDraft) =>
    setEditState((prev) => (prev ? { ...prev, draft: updater(prev.draft) } : prev));

  const startEditing = () => {
    if (!selected) return;
    setEditState({
      recipeId: selected.id,
      draft: {
        title: selected.title,
        source: selected.source,
        basePortions: selected.basePortions,
        ingredients: selected.ingredients.map((ing) => ({ id: ing.id, raw: ing.raw })),
        steps: [...selected.steps],
      },
    });
  };

  const saveEditing = async () => {
    if (!selected || !editingDraft || savingEdit) return;
    const draft = editingDraft;
    const ingredients = draft.ingredients.filter((ing) => ing.raw.trim() !== "");
    if (!draft.title.trim() || ingredients.length === 0) return;
    setSavingEdit(true);
    try {
      await onSaveRecipeEdit(selected.id, {
        title: draft.title.trim(),
        source: draft.source.trim(),
        base_portions: draft.basePortions,
        ingredients,
        steps: draft.steps.filter((s) => s.trim() !== ""),
      });
      setEditState(null);
    } catch (err) {
      console.error(err);
    } finally {
      setSavingEdit(false);
    }
  };

  const deleteCurrentRecipe = () => {
    if (!selected) return;
    if (!window.confirm(`Delete "${selected.title}"? This cannot be undone.`)) return;
    onDeleteRecipe(selected.id)
      .then(() => {
        setSelectedId(null);
        setEditState(null);
      })
      .catch(console.error);
  };

  const detail = selected ? (() => {
    const sourceIsUrl = /^https?:\/\//.test(selected.source);

    // per-ingredient stock state, grouped for the Ingredients tab
    type RowState = "ok" | "missing" | "unmapped" | "staple";
    type Row = { ing: (typeof selected.ingredients)[number]; item?: Item; req?: number; state: RowState; missing: number };
    const rows = selected.ingredients.map((ing) => {
      const item = ing.itemId ? items.find((i) => i.id === ing.itemId) : undefined;
      const req = scaledAmount(ing, selected, portions);
      let state: RowState = "staple";
      let missing = 0;
      if (ing.tracked) {
        if (!item) state = "unmapped";
        else if (ingredientInStock(ing, selected, portions, item)) state = "ok";
        else {
          state = "missing";
          missing = !isBinary(item) && req != null ? missingAmount(ing, selected, portions, item) : 0;
        }
      }
      return { ing, item, req, state, missing };
    });

    // display units: plain ingredients, plus "rice or naan" alternative
    // groups rendered as one card whose options are pickable
    type Unit =
      | { kind: "single"; key: string; row: Row }
      | { kind: "group"; key: string; rows: Row[] };
    const units: Unit[] = [];
    const seenGroups = new Set<string>();
    selected.ingredients.forEach((ing, index) => {
      if (ing.altGroup) {
        if (seenGroups.has(ing.altGroup)) return;
        seenGroups.add(ing.altGroup);
        units.push({ kind: "group", key: ing.altGroup, rows: rows.filter((r) => r.ing.altGroup === ing.altGroup) });
        return;
      }
      units.push({ kind: "single", key: ing.id, row: rows[index] });
    });
    const groupUnitState = (groupRows: Row[]): RowState => {
      if (groupRows.every((r) => r.state === "staple")) return "staple";
      if (groupRows.some((r) => r.state === "ok")) return "ok";
      return "missing";
    };
    const missingRows = units.filter((u) =>
      u.kind === "single" ? u.row.state === "missing" || u.row.state === "unmapped" : groupUnitState(u.rows) === "missing"
    );
    const okRows = units.filter((u) =>
      u.kind === "single" ? u.row.state === "ok" : groupUnitState(u.rows) === "ok"
    );
    const stapleRows = units.filter((u) =>
      u.kind === "single" ? u.row.state === "staple" : groupUnitState(u.rows) === "staple"
    );
    const trackedCount = missingRows.length + okRows.length;
    const stockPct = trackedCount > 0 ? Math.round((okRows.length / trackedCount) * 100) : 100;

    const renderMissingRow = ({ ing, item, req, state, missing }: Row) => (
      <div className="ing-card missing">
        <span className="ing-icon" aria-hidden="true">{state === "unmapped" ? "?" : "!"}</span>
        <div className="ing-main">
          <div className="ing-name">{item ? item.name : baseIngredientName(ing.raw)}</div>
          <div className="ing-sub">
            {state === "unmapped"
              ? req != null
                ? `need ${formatQty(req, ing.unit, true)} · not in your pantry yet`
                : "not in your pantry yet"
              : item && isBinary(item)
                ? req != null ? `need ${formatQty(req, item?.unit, true)}` : ""
                : `need ${req != null ? formatQty(req, item?.unit, true) : ""} \u00B7 have ${formatQty(item?.quantity ?? 0, item?.unit, true)}`}
          </div>
          {state === "unmapped" && ing.suggestion && (
            <div className="ing-actions">
              <span className="suggestion">
                {ing.suggestion}
                <button
                  aria-label={`Accept ${ing.suggestion}`}
                  onClick={() => onMatchIngredient(selected.id, ing.id, ing.suggestion!)}
                >
                  <IconCheck size={13} />
                </button>
              </span>
            </div>
          )}
        </div>
        {state === "unmapped" ? (
          ing.suggestion ? undefined : <button className="btn btn-ghost btn-sm">Match</button>
        ) : (
          <span className="ing-pill lacking">
            {item && !isBinary(item) ? `missing ${formatQty(missing, item.unit, true)}` : "not in stock"}
          </span>
        )}
      </div>
    );

    const advanceStep = () => {
      const last = selected.steps.length - 1;
      if (activeStep == null) setActiveStep(0);
      else if (activeStep >= last) setActiveStep(null);
      else setActiveStep(activeStep + 1);
    };

    const stepLabel =
      activeStep == null ? "Start cooking" : activeStep >= selected.steps.length - 1 ? "Finish" : "Next step";

    const canSaveEditing =
      editingDraft != null &&
      editingDraft.title.trim() !== "" &&
      editingDraft.ingredients.some((ing) => ing.raw.trim() !== "");

    return (
      <>
        <div className="detail-actions">
          {editingDraft ? (
            <>
              <button className="btn btn-ghost btn-sm" onClick={() => setEditState(null)} disabled={savingEdit}>
                Cancel
              </button>
              <button className="btn btn-danger btn-sm" onClick={deleteCurrentRecipe} disabled={savingEdit}>
                Delete
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={saveEditing}
                disabled={!canSaveEditing || savingEdit}
              >
                {savingEdit ? "Saving…" : "Save"}
              </button>
            </>
          ) : (
            <button className="btn btn-ghost btn-sm" onClick={startEditing}>
              <IconPencil size={14} />
              Edit
            </button>
          )}
        </div>

        {editingDraft ? (
          <EditRecipeForm draft={editingDraft} setDraft={setDraft} />
        ) : (
        <>
        {selected.imageUrl && <img className="sheet-hero" src={selected.imageUrl} alt="" />}
        <h2 className="sheet-title">{selected.title}</h2>
        <p className="sheet-sub">{selected.source}</p>

        <RecipeMeta recipe={selected} />

        <div className="detail-tabs">
          <div className="detail-tabs-row">
            <button
              className={detailTab === "ingredients" ? "dtab active" : "dtab"}
              onClick={() => setDetailTab("ingredients")}
            >
              Ingredients
            </button>
            <button
              className={detailTab === "recipe" ? "dtab active" : "dtab"}
              onClick={() => setDetailTab("recipe")}
            >
              Recipe
            </button>
            {sourceIsUrl && (
              <button
                className="dtab"
                onClick={() => window.open(selected.source, "_blank", "noopener")}
                title="Open the recipe's source webpage"
              >
                Webpage <span className="dtab-link">&#8599;</span>
              </button>
            )}
          </div>
          <div className="detail-tab-band" aria-hidden="true" />
        </div>

        {detailTab === "ingredients" ? (
          <>
            <div className="qty-stepper">
              <button onClick={() => onPortionsChange(Math.max(1, portions - 1))} aria-label="Fewer portions">
                <IconMinus size={18} />
              </button>
              <span className="value">{portions} portions</span>
              <button onClick={() => onPortionsChange(Math.min(12, portions + 1))} aria-label="More portions">
                <IconPlus size={18} />
              </button>
            </div>

            <div className="stock-summary">
              <div className="stock-summary-row">
                <span className="stock-label">Pantry check</span>
                <span className="stock-value">
                  {okRows.length} of {trackedCount} in stock
                </span>
              </div>
              <div className="stock-bar">
                <div className="stock-bar-fill" style={{ width: `${stockPct}%` }} />
              </div>
            </div>

            {missingRows.length > 0 && (
              <>
                <div className="ing-group-header missing">
                  <span className="dot" aria-hidden="true" />
                  Missing &middot; {missingRows.length}
                  <span className="spacer" />
                  <button
                    className={addedId === selected.id ? "btn btn-sm added" : "btn btn-primary btn-sm"}
                    onClick={() => doAddMissing(selected)}
                  >
                    {addedId === selected.id ? "Added" : "Add to list"}
                  </button>
                </div>
                {missingRows.map((u) =>
                  u.kind === "group" ? (
                    <AltGroupCard
                      key={u.key}
                      rows={u.rows}
                      bucket="missing"
                      recipeId={selected.id}
                      onMatch={onMatchIngredient}
                      onSelect={onSelectIngredient}
                    />
                  ) : (
                    <Fragment key={u.key}>{renderMissingRow(u.row)}</Fragment>
                  )
                )}
              </>
            )}

            {okRows.length > 0 && (
              <>
                <div className="ing-group-header ok">
                  <span className="dot" aria-hidden="true" />
                  In stock &middot; {okRows.length}
                </div>
                {okRows.map((u) =>
                  u.kind === "group" ? (
                    <AltGroupCard
                      key={u.key}
                      rows={u.rows}
                      bucket="ok"
                      recipeId={selected.id}
                      onMatch={onMatchIngredient}
                      onSelect={onSelectIngredient}
                    />
                  ) : (
                    <Fragment key={u.key}>
                      <div className="ing-card ok">
                        <span className="ing-check-circle" aria-hidden="true">
                          <IconCheck size={12} />
                        </span>
                        <div className="ing-main">
                          <div className="ing-name">{u.row.item!.name}</div>
                          {u.row.req != null && (
                            <div className="ing-sub">need {formatQty(u.row.req, u.row.item!.unit, true)}</div>
                          )}
                        </div>
                        <span className="ing-pill ok">in stock</span>
                      </div>
                    </Fragment>
                  )
                )}
              </>
            )}

            {stapleRows.length > 0 && stapleRows.map((u) => (
              <div key={u.key} className="ing-card staple">
                <span className="ing-icon" aria-hidden="true" />
                <div className="ing-main">
                  <div className="ing-name">
                    {u.kind === "group"
                      ? u.rows.map((r) => baseIngredientName(r.ing.raw)).join(" or ")
                      : baseIngredientName(u.row.ing.raw)}
                  </div>
                </div>
                <div className="ing-status always">always in stock</div>
              </div>
            ))}
          </>
        ) : (
          <>
            <h3 className="sheet-h3">Steps</h3>
            <div className="step-cards">
              {selected.steps.map((step, i) => (
                <button
                  key={i}
                  className={activeStep === i ? "step-card active" : "step-card"}
                  onClick={() => setActiveStep(activeStep === i ? null : i)}
                  aria-pressed={activeStep === i}
                >
                  <span className="step-num">{i + 1}</span>
                  <span className="step-text">
                    {stepSegments(step, selected.stepIngredients?.[i], selected, portions).map(
                      (segment, j) =>
                        segment.isQty ? (
                          <span key={j} className="step-qty">
                            {segment.text}
                          </span>
                        ) : (
                          segment.text
                        )
                    )}
                  </span>
                </button>
              ))}
            </div>
            <button className="btn btn-primary btn-block next-step-btn" onClick={advanceStep}>
              {stepLabel} <span className="next-arrow" aria-hidden="true">&#8594;</span>
            </button>
          </>
        )}
        </>
        )}
      </>
    );
  })() : null;

  return (
    <div className="screen">
      <header className="screen-header">
        <h1 className="screen-title">Recipes</h1>
        <div className="header-actions">
          <button className="icon-btn" onClick={() => setSettingsMenuOpen(true)} aria-label="Settings">
            <IconGear size={19} />
          </button>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </header>

      <div className={twoPane ? "split" : "recipes-body"}>
        <div className="split-master">
          {twoPane ? (
            <div className="master-toolbar">
              <div className="qty-stepper">
                <button onClick={() => onPortionsChange(Math.max(1, portions - 1))} aria-label="Fewer portions">
                  <IconMinus size={18} />
                </button>
                <span className="value">{portions} portions</span>
                <button onClick={() => onPortionsChange(Math.min(12, portions + 1))} aria-label="More portions">
                  <IconPlus size={18} />
                </button>
              </div>
              <button className="btn btn-primary" onClick={() => setImportOpen(true)}>
                <IconPlus size={16} />
                Add recipe
              </button>
            </div>
          ) : (
            <div className="qty-stepper">
              <button onClick={() => onPortionsChange(Math.max(1, portions - 1))} aria-label="Fewer portions">
                <IconMinus size={18} />
              </button>
              <span className="value">{portions} portions</span>
              <button onClick={() => onPortionsChange(Math.min(12, portions + 1))} aria-label="More portions">
                <IconPlus size={18} />
              </button>
            </div>
          )}

          <div className="search">
        <IconSearch size={17} />
        <input
          type="search"
          placeholder="Search recipes"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {filterChips.length > 0 && (
        <div className="chip-row" role="group" aria-label="Filter by category">
          {filterChips.map((filter) => (
            <button
              key={filter}
              className={activeFilters.includes(filter) ? "chip active" : "chip"}
              onClick={() => toggleFilter(filter)}
              aria-pressed={activeFilters.includes(filter)}
            >
              {filter}
            </button>
          ))}
        </div>
      )}

      {!twoPane && (
        <button className="btn btn-primary btn-block" onClick={() => setImportOpen(true)}>
          <IconPlus size={16} />
          Add recipe
        </button>
      )}

      <div className="section-title-row">
        <h2 className="section-title">
          {activeFilters.length > 0 ? "Results" : "Your recipes"} · {filteredRecipes.length}
        </h2>
        <div className="segmented segmented-compact" aria-label="Sort recipes">
          {SORTS.map((s) => (
            <button key={s.id} className={sort === s.id ? "active" : ""} onClick={() => setSort(s.id)}>
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="card-grid">
      {filteredRecipes.map((recipe) => {
        const mp = maxPortions(recipe, items);
        const cookable = mp >= portions;
        const time = formatMinutes(recipe.totalMinutes);
        return (
          <button
            key={recipe.id}
            className={`card recipe-card${cookable ? "" : " dim"}${selectedId === recipe.id ? " selected" : ""}`}
            onClick={() => {
              setSelectedId(recipe.id);
              setActiveStep(null);
            }}
          >
            {recipe.imageUrl ? (
              <span className="recipe-photo-wrap">
                <img className="recipe-photo" src={recipe.imageUrl} alt="" loading="lazy" />
                <span className="recipe-photo-overlay">
                  <span className="item-name">{recipe.title}</span>
                  {time && (
                    <span className="meta-chip on-photo">
                      <IconClock size={12} />
                      {time}
                    </span>
                  )}
                </span>
                <span className={cookable ? "badge cookable floating" : "badge missing floating"}>
                  {cookable ? "Cookable" : `makes ${mp === Infinity ? "∞" : mp}`}
                </span>
              </span>
            ) : (
              <>
                <div className="info">
                  <div className="item-name">{recipe.title}</div>
                  <div className="item-sub">
                    {recipe.basePortions} portions · {recipe.ingredients.length} ingredients
                    {time ? ` · ${time}` : ""}
                  </div>
                </div>
                <span className={cookable ? "badge cookable" : "badge missing"}>
                  {cookable ? "Cookable" : `makes ${mp === Infinity ? "∞" : mp}`}
                </span>
              </>
            )}
          </button>
        );
      })}

      {recipes.length > 0 && filteredRecipes.length === 0 && (
        <p className="empty-state">Nothing matches the current search and filters.</p>
      )}
      </div>

        </div>
        {twoPane && (
          <aside className="split-detail">
            {detail ?? <div className="empty-state">Select a recipe to see ingredients and steps.</div>}
          </aside>
        )}
      </div>

      {!twoPane && selected && (
        <Sheet onClose={() => setSelectedId(null)}>{detail}</Sheet>
      )}

      {importOpen && (
        <Sheet onClose={() => setImportOpen(false)}>
          <h2 className="sheet-title">Add recipe</h2>
          <p className="sheet-sub">Paste a link or the recipe text</p>

          <div className="segmented">
            <button className={kind === "link" ? "active" : ""} onClick={() => setKind("link")}>
              Link
            </button>
            <button className={kind === "text" ? "active" : ""} onClick={() => setKind("text")}>
              Text
            </button>
          </div>

          {kind === "link" ? (
            <input
              className="import-input"
              type="url"
              placeholder="https://…"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          ) : (
            <textarea
              className="import-area"
              placeholder="Paste the recipe text…"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          )}

          <div className="sheet-actions">
            <button className="btn btn-ghost" onClick={() => setImportOpen(false)}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!value.trim() || busy} onClick={doImport}>
              {busy ? "Importing…" : "Import"}
            </button>
          </div>
        </Sheet>
      )}

      {settingsMenuOpen && (
        <Sheet onClose={() => setSettingsMenuOpen(false)}>
          <h2 className="sheet-title">Settings</h2>
          <p className="sheet-sub">Recipe tools and pantry matching.</p>
          <div className="settings-menu">
            <button
              className="settings-menu-row"
              onClick={() => {
                setSettingsMenuOpen(false);
                setSettingsOpen(true);
              }}
            >
              <span>
                Model settings
                <span className="settings-menu-sub">Local or cloud model for recipe imports</span>
              </span>
              <span className="settings-menu-chevron">›</span>
            </button>
            <button
              className="settings-menu-row"
              onClick={() => {
                setSettingsMenuOpen(false);
                setMissingOpen(true);
              }}
            >
              <span>
                Missing items
                <span className="settings-menu-sub">
                  Match ingredients that no inventory item covers yet
                </span>
              </span>
              <span className="settings-menu-chevron">›</span>
            </button>
          </div>
        </Sheet>
      )}

      {settingsOpen && (
        <ModelSettingsSheet
          task="recipes"
          settings={settings}
          localModels={models.local}
          llmAvailable={models.llmAvailable}
          onSave={onSaveSettings}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {missingOpen && (
        <MissingItemsSheet
          items={items}
          categories={categorySuggestions}
          onMerge={onMergeMissing}
          onCreateAndMerge={onCreateMissingItem}
          onClose={() => setMissingOpen(false)}
        />
      )}
    </div>
  );
}

interface AltRow {
  ing: Ingredient;
  item?: Item;
  state: "ok" | "missing" | "unmapped" | "staple";
}

interface AltGroupCardProps {
  rows: AltRow[];
  bucket: "missing" | "ok";
  recipeId: string;
  onMatch: (recipeId: string, ingredientId: string, itemName: string) => void;
  onSelect: (recipeId: string, ingredientId: string) => void;
}

/** "Basmati rice or naan": and/or alternatives from one source line.
 *  Exactly one option is the pick — it is the one that goes on the
 *  shopping list when it's empty and the one cooking deducts. */
function AltGroupCard({ rows, bucket, recipeId, onMatch, onSelect }: AltGroupCardProps) {
  const label = rows.map((r) => r.item?.name ?? baseIngredientName(r.ing.raw)).join(" or ");
  const hasPick = rows.some((r) => r.ing.selected);
  const optionLabel = (r: AltRow) =>
    r.state === "ok" ? "in stock" : r.state === "unmapped" ? "unmapped" : "not in stock";
  const pickable = rows.filter((r) => r.state !== "staple");
  return (
    <div className={`ing-card alt-group ${bucket}`}>
      <span className={bucket === "ok" ? "ing-check-circle" : "ing-icon"} aria-hidden="true">
        {bucket === "ok" ? <IconCheck size={12} /> : "!"}
      </span>
      <div className="ing-main">
        <div className="ing-name">{label}</div>
        <div className="alt-options" role="group" aria-label={`Pick one: ${label}`}>
          {pickable.map((r) => (
            <button
              key={r.ing.id}
              className={r.ing.selected ? "alt-chip selected" : "alt-chip"}
              onClick={() => onSelect(recipeId, r.ing.id)}
              aria-pressed={Boolean(r.ing.selected)}
              title={optionLabel(r)}
            >
              <span className="alt-dot" aria-hidden="true" />
              <span className="alt-name">{r.item?.name ?? baseIngredientName(r.ing.raw)}</span>
              <span className={r.state === "ok" ? "alt-state ok" : "alt-state"}>{optionLabel(r)}</span>
            </button>
          ))}
        </div>
        <div className="ing-sub">
          {hasPick
            ? "the pick goes on the list when it's empty"
            : bucket === "ok"
              ? "serve with whichever you like"
              : "pick which one to buy"}
        </div>
        {rows
          .filter((r) => r.state === "unmapped" && r.ing.suggestion)
          .map((r) => (
            <div className="ing-actions" key={r.ing.id}>
              <span className="suggestion">
                {r.ing.suggestion}
                <button
                  aria-label={`Accept ${r.ing.suggestion}`}
                  onClick={() => onMatch(recipeId, r.ing.id, r.ing.suggestion!)}
                >
                  <IconCheck size={13} />
                </button>
              </span>
            </div>
          ))}
      </div>
    </div>
  );
}

/** Manual edit form: title, source and base portions, plus the ingredient
 *  and step lists with per-line remove buttons and add buttons. Every line
 *  is plain text; the backend re-parses ingredient lines on save. */
function EditRecipeForm({
  draft,
  setDraft,
}: {
  draft: RecipeDraft;
  setDraft: (updater: (d: RecipeDraft) => RecipeDraft) => void;
}) {
  const setIngredient = (index: number, raw: string) =>
    setDraft((d) => ({
      ...d,
      ingredients: d.ingredients.map((ing, i) => (i === index ? { ...ing, raw } : ing)),
    }));
  const removeIngredient = (index: number) =>
    setDraft((d) => ({ ...d, ingredients: d.ingredients.filter((_, i) => i !== index) }));
  const setStep = (index: number, text: string) =>
    setDraft((d) => ({ ...d, steps: d.steps.map((s, i) => (i === index ? text : s)) }));
  const removeStep = (index: number) =>
    setDraft((d) => ({ ...d, steps: d.steps.filter((_, i) => i !== index) }));

  return (
    <div className="edit-form">
      <label className="edit-label" htmlFor="edit-title">Title</label>
      <input
        id="edit-title"
        className="import-input"
        value={draft.title}
        onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
      />

      <label className="edit-label" htmlFor="edit-source">Source</label>
      <input
        id="edit-source"
        className="import-input"
        value={draft.source}
        onChange={(e) => setDraft((d) => ({ ...d, source: e.target.value }))}
      />

      <label className="edit-label">Ingredient amounts are for</label>
      <div className="qty-stepper">
        <button
          onClick={() => setDraft((d) => ({ ...d, basePortions: Math.max(1, d.basePortions - 1) }))}
          aria-label="Fewer base portions"
        >
          <IconMinus size={18} />
        </button>
        <span className="value">{draft.basePortions} portions</span>
        <button
          onClick={() => setDraft((d) => ({ ...d, basePortions: d.basePortions + 1 }))}
          aria-label="More base portions"
        >
          <IconPlus size={18} />
        </button>
      </div>

      <label className="edit-label">Ingredients</label>
      {draft.ingredients.map((ing, index) => (
        <div className="edit-row" key={ing.id ?? `new-${index}`}>
          <input
            className="import-input edit-input"
            value={ing.raw}
            placeholder="e.g. 2 Zwiebeln"
            onChange={(e) => setIngredient(index, e.target.value)}
          />
          <button
            className="btn btn-ghost btn-sm edit-remove"
            aria-label="Remove ingredient"
            onClick={() => removeIngredient(index)}
          >
            <IconX size={14} />
          </button>
        </div>
      ))}
      <button
        className="btn btn-ghost btn-sm edit-add"
        onClick={() => setDraft((d) => ({ ...d, ingredients: [...d.ingredients, { raw: "" }] }))}
      >
        <IconPlus size={14} />
        Add ingredient
      </button>

      <label className="edit-label">Steps</label>
      {draft.steps.map((step, index) => (
        <div className="edit-row" key={`step-${index}`}>
          <textarea
            className="import-area edit-input"
            rows={2}
            value={step}
            placeholder="Describe this step…"
            onChange={(e) => setStep(index, e.target.value)}
          />
          <button
            className="btn btn-ghost btn-sm edit-remove"
            aria-label="Remove step"
            onClick={() => removeStep(index)}
          >
            <IconX size={14} />
          </button>
        </div>
      ))}
      <button
        className="btn btn-ghost btn-sm edit-add"
        onClick={() => setDraft((d) => ({ ...d, steps: [...d.steps, ""] }))}
      >
        <IconPlus size={14} />
        Add step
      </button>
    </div>
  );
}

function RecipeMeta({ recipe }: { recipe: Recipe }) {
  const chips: { label: string; icon?: boolean }[] = [];
  const total = formatMinutes(recipe.totalMinutes);
  const prep = formatMinutes(recipe.prepMinutes);
  const cook = formatMinutes(recipe.cookMinutes);
  if (total && (recipe.prepMinutes == null && recipe.cookMinutes == null)) {
    chips.push({ label: total, icon: true });
  } else {
    if (prep) chips.push({ label: `Prep ${prep}` });
    if (cook) chips.push({ label: `Cook ${cook}` });
    if (total) chips.push({ label: `Total ${total}` });
  }
  if (recipe.cuisine) chips.push({ label: recipe.cuisine });
  if (recipe.category) chips.push({ label: recipe.category });
  return (
    <div className="meta-row">
      {chips.map((chip) => (
        <span key={chip.label} className="meta-chip">
          {chip.icon && <IconClock size={13} />}
          {chip.label}
        </span>
      ))}
      {(recipe.tags ?? []).map((tag) => (
        <span key={tag} className="tag-chip">
          {tag}
        </span>
      ))}
    </div>
  );
}
