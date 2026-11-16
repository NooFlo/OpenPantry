import { useMemo, useState } from "react";
import type { Item, ModelList, Recipe, Settings, SettingsPatch } from "../types";
import { importRecipe, refreshRecipe } from "../api";
import { maxPortions, missingCount, missingAmount, scaledAmount, ingredientInStock } from "../lib/cooking";
import { isBinary } from "../lib/tracking";
import { RECIPE_FILTERS, formatMinutes } from "../lib/tags";
import { useMediaQuery } from "../lib/useMediaQuery";
import Sheet from "../components/Sheet";
import ThemeToggle from "../components/ThemeToggle";
import ModelSettingsSheet from "../components/ModelSettingsSheet";
import {
  IconCheck,
  IconClock,
  IconGear,
  IconMinus,
  IconPlus,
  IconRefresh,
  IconSearch,
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
  onRefresh: (recipe: Recipe) => void;
  onCook: (recipe: Recipe) => void;
  onAddMissing: (recipe: Recipe) => Promise<void>;
  onMatchIngredient: (recipeId: string, ingredientId: string, itemName: string) => void;
  settings: Settings;
  models: ModelList;
  onSaveSettings: (patch: SettingsPatch) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

export default function RecipesScreen({
  recipes,
  items,
  portions,
  onPortionsChange,
  onImport,
  onRefresh,
  onCook,
  onAddMissing,
  onMatchIngredient,
  settings,
  models,
  onSaveSettings,
  theme,
  onToggleTheme,
}: RecipesScreenProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [kind, setKind] = useState<"link" | "text">("link");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [activeFilters, setActiveFilters] = useState<string[]>([]);
  const [sort, setSort] = useState<Sort>("newest");
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [addingId, setAddingId] = useState<string | null>(null);
  const [addedId, setAddedId] = useState<string | null>(null);

  const selected = recipes.find((r) => r.id === selectedId) ?? null;
  const selectedMissing = selected ? missingCount(selected, items, portions) : 0;
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

  const doRefresh = async (recipe: Recipe) => {
    if (refreshingId) return;
    setRefreshingId(recipe.id);
    try {
      const updated = await refreshRecipe(recipe.id);
      onRefresh(updated);
      setSelectedId(updated.id);
    } finally {
      setRefreshingId(null);
    }
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

  const detail = selected ? (
    <>
      {selected.imageUrl && <img className="sheet-hero" src={selected.imageUrl} alt="" />}
      <h2 className="sheet-title">{selected.title}</h2>
      <p className="sheet-sub">{selected.source}</p>

      <RecipeMeta recipe={selected} />

      <div className="qty-stepper">
        <button onClick={() => onPortionsChange(Math.max(1, portions - 1))} aria-label="Fewer portions">
          <IconMinus size={18} />
        </button>
        <span className="value">{portions} portions</span>
        <button onClick={() => onPortionsChange(Math.min(12, portions + 1))} aria-label="More portions">
          <IconPlus size={18} />
        </button>
      </div>

      <div className="ing-list">
        {selected.ingredients.map((ing) => {
          const item = ing.itemId ? items.find((i) => i.id === ing.itemId) : undefined;
          const req = scaledAmount(ing, selected, portions);
          const satisfied = item && ing.tracked ? ingredientInStock(ing, selected, portions, item) : false;
          const missing = item && ing.tracked && !satisfied && req != null && !isBinary(item)
            ? missingAmount(ing, selected, portions, item)
            : 0;
          const rowState = !ing.tracked ? "" : satisfied ? " in-stock" : " not-in-stock";
          return (
            <div key={ing.id} className={`ing-row${rowState}`}>
              {ing.tracked && (
                <span className={satisfied ? "ing-check checked" : "ing-check"} aria-hidden="true">
                  {satisfied && <IconCheck size={12} />}
                </span>
              )}
              <div className="ing-main">
                <div className="ing-name">{item ? item.name : ing.raw}</div>
                {!item && ing.tracked && (
                  <div className="ing-actions">
                    {ing.suggestion ? (
                      <span className="suggestion">
                        {ing.suggestion}
                        <button
                          aria-label={`Accept ${ing.suggestion}`}
                          onClick={() => onMatchIngredient(selected.id, ing.id, ing.suggestion!)}
                        >
                          <IconCheck size={13} />
                        </button>
                      </span>
                    ) : (
                      <button className="btn btn-ghost btn-sm">Match</button>
                    )}
                  </div>
                )}
              </div>
              <div className="ing-right">
                {item && req != null && <span className="ing-qty">{req} {item.unit}</span>}
                {!ing.tracked && <div className="ing-status always">always in stock</div>}
                {item && ing.tracked && !satisfied && (
                  <div className="ing-status lacking">
                    {isBinary(item) ? "not in stock" : `missing ${Math.round(missing * 100) / 100} ${item.unit}`}
                  </div>
                )}
                {item && ing.tracked && satisfied && <div className="ing-status ok">in stock</div>}
              </div>
            </div>
          );
        })}
      </div>

      <h3 className="sheet-h3">Steps</h3>
      <ol className="steps">
        {selected.steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>

      <div className="sheet-actions">
        {selected.source.startsWith("http") && (
          <button
            className="btn btn-ghost"
            disabled={refreshingId === selected.id}
            onClick={() => doRefresh(selected)}
            title="Re-import tags, times and image from the source"
          >
            <IconRefresh size={15} />
            {refreshingId === selected.id ? "Refreshing…" : "Refresh"}
          </button>
        )}
        {selectedMissing > 0 && (
          <button
            className={addedId === selected.id ? "btn btn-primary added" : "btn btn-primary"}
            onClick={() => doAddMissing(selected)}
          >
            {addedId === selected.id ? "Added" : "Add missing to shopping list"}
          </button>
        )}
        <button
          className={selectedMissing > 0 ? "btn btn-ghost" : "btn btn-primary"}
          onClick={() => onCook(selected)}
        >
          Cooked this
        </button>
      </div>
    </>
  ) : null;

  return (
    <div className="screen">
      <header className="screen-header">
        <h1 className="screen-title">Recipes</h1>
        <div className="header-actions">
          <button className="icon-btn" onClick={() => setSettingsOpen(true)} aria-label="Model settings">
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
            onClick={() => setSelectedId(recipe.id)}
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
