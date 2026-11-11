import { useState } from "react";
import type { Item, ModelList, Recipe, Settings, SettingsPatch } from "../types";
import { importRecipe } from "../api";
import { maxPortions, missingCount, missingAmount, scaledAmount } from "../lib/cooking";
import Sheet from "../components/Sheet";
import ThemeToggle from "../components/ThemeToggle";
import ModelSettingsSheet from "../components/ModelSettingsSheet";
import { IconCheck, IconGear, IconMinus, IconPlus } from "../components/Icons";

interface RecipesScreenProps {
  recipes: Recipe[];
  items: Item[];
  portions: number;
  onPortionsChange: (p: number) => void;
  onImport: (recipe: Recipe) => void;
  onCook: (recipe: Recipe) => void;
  onAddMissing: (recipe: Recipe) => void;
  onMatchIngredient: (recipeId: string, ingredientId: string, itemName: string) => void;
  onMarkUntracked: (recipeId: string, ingredientId: string) => void;
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
  onCook,
  onAddMissing,
  onMatchIngredient,
  onMarkUntracked,
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

  const selected = recipes.find((r) => r.id === selectedId) ?? null;
  const selectedMissing = selected ? missingCount(selected, items, portions) : 0;

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

      <div className="qty-stepper">
        <button onClick={() => onPortionsChange(Math.max(1, portions - 1))} aria-label="Fewer portions">
          <IconMinus size={18} />
        </button>
        <span className="value">{portions} portions</span>
        <button onClick={() => onPortionsChange(Math.min(12, portions + 1))} aria-label="More portions">
          <IconPlus size={18} />
        </button>
      </div>

      <button className="btn btn-primary btn-block" onClick={() => setImportOpen(true)}>
        <IconPlus size={16} />
        Add recipe
      </button>

      <h2 className="section-title">Your recipes</h2>

      {recipes.map((recipe) => {
        const mp = maxPortions(recipe, items);
        const cookable = mp >= portions;
        return (
          <button
            key={recipe.id}
            className={cookable ? "card recipe-card" : "card recipe-card dim"}
            onClick={() => setSelectedId(recipe.id)}
          >
            <div className="info">
              <div className="item-name">{recipe.title}</div>
              <div className="item-sub">
                {recipe.basePortions} portions · {recipe.ingredients.length} ingredients
              </div>
            </div>
            <span className={cookable ? "badge cookable" : "badge missing"}>
              {cookable ? "Cookable" : `makes ${mp === Infinity ? "∞" : mp}`}
            </span>
          </button>
        );
      })}

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

      {selected && (
        <Sheet onClose={() => setSelectedId(null)}>
          <h2 className="sheet-title">{selected.title}</h2>
          <p className="sheet-sub">{selected.source}</p>

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
              const missing = item && req != null ? missingAmount(ing, selected, portions, item) : 0;
              const showMissing = missing > 0.001;
              return (
                <div key={ing.id} className="ing-row">
                  <div className="ing-main">
                    <div className="ing-name">{item ? item.name : ing.raw}</div>
                    {!ing.tracked && <div className="ing-status unmapped">not tracked</div>}
                    {ing.tracked && !item && (
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
                        <button className="btn btn-ghost btn-sm" onClick={() => onMarkUntracked(selected.id, ing.id)}>
                          Don't track
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="ing-right">
                    {item && req != null && <span className="ing-qty">{req} {item.unit}</span>}
                    {item && showMissing && (
                      <div className="ing-status lacking">
                        missing {Math.round(missing * 100) / 100} {item.unit}
                      </div>
                    )}
                    {item && !showMissing && <div className="ing-status ok">in stock</div>}
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
            {selectedMissing > 0 && (
              <button className="btn btn-primary" onClick={() => onAddMissing(selected)}>
                Add missing to shopping list
              </button>
            )}
            <button
              className={selectedMissing > 0 ? "btn btn-ghost" : "btn btn-primary"}
              onClick={() => onCook(selected)}
            >
              Cooked this
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
