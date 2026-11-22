import { useEffect, useMemo, useState } from "react";
import type { DragEvent } from "react";
import type { PlanPerson, PreparedMeal, Recipe, Item, PlanShoppingEntry, PlanningFill, PlanningMeal, WeekPlan } from "../types";
import {
  addPlanFill,
  addPlanMeal,
  addPlanPerson,
  addPreparedMeal,
  deletePlanFill,
  deletePlanMeal,
  deletePlanPerson,
  deletePreparedMeal,
  fetchPlanShoppingList,
  fetchWeekPlan,
  pushPlanShoppingList,
  togglePlanMealPerson,
} from "../api";
import Sheet from "../components/Sheet";
import StepperRow from "../components/StepperRow";
import ThemeToggle from "../components/ThemeToggle";
import { IconPlus, IconStar, IconX } from "../components/Icons";
import { maxPortions } from "../lib/cooking";

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MEAL_SUGGESTIONS = ["Breakfast", "Lunch", "Dinner", "Snack"];

interface PlanningScreenProps {
  recipes: Recipe[];
  recipesLoading?: boolean;
  items: Item[];
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

function mondayOf(d: Date): string {
  const date = new Date(d);
  const day = (date.getDay() + 6) % 7;
  date.setDate(date.getDate() - day);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

type DragPayload = { kind: "recipe" | "prepared"; id: string };

function parseDrag(text: string | undefined): DragPayload | null {
  const match = text?.match(/^(recipe|prepared):(.+)$/);
  return match ? { kind: match[1] as "recipe" | "prepared", id: match[2] } : null;
}

interface FillSheetState {
  drag: DragPayload;
  mealId?: string;
}

export default function PlanningScreen({ recipes, items, theme, onToggleTheme }: PlanningScreenProps) {
  const [week, setWeek] = useState(() => mondayOf(new Date()));
  const [plan, setPlan] = useState<WeekPlan | null>(null);
  const [addMealDay, setAddMealDay] = useState<number | null>(null);
  const [fillSheet, setFillSheet] = useState<FillSheetState | null>(null);
  const [personsSheet, setPersonsSheet] = useState(false);
  const [preparedSheet, setPreparedSheet] = useState(false);
  const [weekListSheet, setWeekListSheet] = useState(false);
  const [shoppingEntries, setShoppingEntries] = useState<PlanShoppingEntry[] | null>(null);
  const [pushed, setPushed] = useState(false);
  const [editingMeal, setEditingMeal] = useState<string | null>(null);
  const [favOpen, setFavOpen] = useState(false);
  const [allOpen, setAllOpen] = useState(true);

  useEffect(() => {
    fetchWeekPlan(week).then(setPlan).catch(console.error);
  }, [week]);

  useEffect(() => {
    if (!weekListSheet) {
      setShoppingEntries(null);
      setPushed(false);
    }
  }, [weekListSheet]);

  const openFill = (drag: DragPayload, mealId?: string) => setFillSheet({ drag, mealId });

  const favorites = useMemo(() => recipes.filter((r) => r.favorite), [recipes]);

  /** recipes where every tracked ingredient is covered by pantry stock
   *  (cookable for at least one portion) — shown with a green ring */
  const inStock = useMemo(() => {
    const map = new Map<string, boolean>();
    for (const r of recipes) map.set(r.id, maxPortions(r, items) >= 1);
    return map;
  }, [recipes, items]);

  /** Direct drop placement: no sheet. A drop on a person's half targets that
   * person (one portion); a drop on the whole field feeds the meal's persons
   * — or all persons when none are attached yet — one portion each, capped
   * by how many portions of a prepared meal are left. */
  const doPlace = async (
    drag: DragPayload,
    meal: PlanningMeal,
    personId: string | null,
    planState: WeekPlan | null = plan
  ) => {
    const all = planState?.persons ?? [];
    const targets = personId
      ? [personId]
      : meal.persons.length > 0
        ? meal.persons.map((p) => p.id)
        : all.map((p) => p.id);
    const prepared = drag.kind === "prepared" ? planState?.prepared.find((p) => p.id === drag.id) : undefined;
    const wanted = Math.max(1, targets.length);
    const portions = personId ? 1 : prepared ? Math.min(wanted, Math.max(1, prepared.available)) : wanted;
    const updated = await addPlanFill(meal.id, {
      recipeId: drag.kind === "recipe" ? drag.id : undefined,
      preparedId: drag.kind === "prepared" ? drag.id : undefined,
      portions,
      prepMultiplier: 0,
      personId: personId ?? undefined,
      personIds: targets,
    });
    setPlan(updated);
  };

  /** Drop on a day column: into the only meal, auto-create one when the day
   * is empty (all persons), chooser sheet only when genuinely ambiguous. */
  const handleDayDrop = async (day: number, text: string | undefined) => {
    const drag = parseDrag(text);
    if (!drag) return;
    const dayMeals = mealsByDay[day];
    if (dayMeals.length === 1) {
      await doPlace(drag, dayMeals[0], null);
      return;
    }
    if (dayMeals.length > 1) {
      openFill(drag);
      return;
    }
    const updated = await addPlanMeal(week, day, "Lunch", (plan?.persons ?? []).map((p) => p.id));
    const created = updated.meals.filter((m) => m.day === day).slice(-1)[0];
    if (created) {
      await doPlace(drag, created, null, updated);
    } else {
      setPlan(updated);
    }
  };

  const mealsByDay = useMemo(() => {
    const days: PlanningMeal[][] = Array.from({ length: 7 }, () => []);
    (plan?.meals ?? []).forEach((m) => days[m.day]?.push(m));
    return days;
  }, [plan]);

  return (
    <div className="screen plan-screen">
      <header className="screen-header">
        <h1 className="screen-title">Planning</h1>
        <div className="header-actions">
          <button className="btn btn-ghost btn-sm" onClick={() => setPersonsSheet(true)}>
            Persons
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => setWeekListSheet(true)}>
            Week list
          </button>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </header>

      <div className="week-nav">
        <button className="icon-btn" aria-label="Previous week" onClick={() => setWeek(addDays(week, -7))}>
          ‹
        </button>
        <span className="week-label">
          {`Week of ${week}`} · {(plan?.meals ?? []).filter((m) => m.fills.length > 0).length} planned
        </span>
        <button className="icon-btn" aria-label="Next week" onClick={() => setWeek(addDays(week, 7))}>
          ›
        </button>
      </div>

      <div className="plan-layout">
        <aside className="plan-menu">
          <div className="plan-menu-head">
            <h2 className="section-title">Prepared meals</h2>
            <button className="icon-btn" aria-label="Add prepared meal" onClick={() => setPreparedSheet(true)}>
              <IconPlus size={16} />
            </button>
          </div>
          {(plan?.prepared ?? []).length === 0 ? (
            <div className="plan-empty">Nothing prepped yet — add frozen meals or leftovers, or use a Food Prep multiplier when planning a recipe.</div>
          ) : (
            <div className="plan-menu-list">
              {plan!.prepared.map((p) => (
                <PreparedRow
                  key={p.id}
                  prepared={p}
                  onPlace={() => openFill({ kind: "prepared", id: p.id })}
                  onDelete={() => deletePreparedMeal(p.id).then(setPlan)}
                />
              ))}
            </div>
          )}
          <h2 className="section-title">Recipes</h2>
          <div className="plan-group">
            <button
              className="plan-group-head"
              aria-expanded={favOpen}
              onClick={() => setFavOpen((v) => !v)}
            >
              <IconStar size={14} filled />
              <span className="plan-group-title">Favorites</span>
              <span className="plan-group-count">{favorites.length}</span>
              <span className={favOpen ? "plan-group-chevron open" : "plan-group-chevron"}>‹</span>
            </button>
            {favOpen && (
              <div className="plan-menu-list">
                {favorites.map((r) => (
                  <RecipePick key={r.id} recipe={r} inStock={inStock.get(r.id) ?? false} onPick={() => openFill({ kind: "recipe", id: r.id })} />
                ))}
                {favorites.length === 0 && (
                  <div className="plan-empty">Star recipes to pin them here.</div>
                )}
              </div>
            )}
          </div>
          <div className="plan-group">
            <button
              className="plan-group-head"
              aria-expanded={allOpen}
              onClick={() => setAllOpen((v) => !v)}
            >
              <span className="plan-group-title">All recipes</span>
              <span className="plan-group-count">{recipes.length}</span>
              <span className={allOpen ? "plan-group-chevron open" : "plan-group-chevron"}>‹</span>
            </button>
            {allOpen && (
              <div className="plan-menu-list">
                {recipes.map((r) => (
                  <RecipePick key={r.id} recipe={r} inStock={inStock.get(r.id) ?? false} onPick={() => openFill({ kind: "recipe", id: r.id })} />
                ))}
                {recipes.length === 0 && <div className="plan-empty">No recipes saved yet.</div>}
              </div>
            )}
          </div>
        </aside>

        <div className="plan-board">
          {DAY_NAMES.map((name, day) => {
            const dayMeals = mealsByDay[day] ?? [];
            const lunch = dayMeals.find((m) => m.meal === "Lunch");
            const dinner = dayMeals.find((m) => m.meal === "Dinner");
            const extras = dayMeals.filter((m) => m !== lunch && m !== dinner);
            return (
            <div
              key={name}
              className="plan-day"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                handleDayDrop(day, e.dataTransfer.getData("text/plain"));
              }}
            >
              <div className="plan-day-head">
                <span className="plan-day-name">{name}</span>
                <span className="plan-day-date">{addDays(week, day).slice(5)}</span>
                <button className="icon-btn" aria-label={`Add meal on ${name}`} onClick={() => setAddMealDay(day)}>
                  <IconPlus size={15} />
                </button>
              </div>
              {lunch && (
                <MealCard
                  key={lunch.id}
                  meal={lunch}
                  planPersons={plan?.persons ?? []}
                  onPlace={(drag, personId) => doPlace(drag, lunch, personId)}
                  onDelete={() => deletePlanMeal(lunch.id).then(setPlan)}
                  onRemoveFill={(fill) => deletePlanFill(fill.id).then(setPlan)}
                  onChangePersons={() => {
                    setEditingMeal(lunch.id);
                    setPersonsSheet(true);
                  }}
                />
              )}
              {dinner && (
                <MealCard
                  key={dinner.id}
                  meal={dinner}
                  planPersons={plan?.persons ?? []}
                  onPlace={(drag, personId) => doPlace(drag, dinner, personId)}
                  onDelete={() => deletePlanMeal(dinner.id).then(setPlan)}
                  onRemoveFill={(fill) => deletePlanFill(fill.id).then(setPlan)}
                  onChangePersons={() => {
                    setEditingMeal(dinner.id);
                    setPersonsSheet(true);
                  }}
                />
              )}
              {extras.length > 0 && (
                <div className="plan-day-extras">
                  {extras.map((meal) => (
                    <MealCard
                      key={meal.id}
                      meal={meal}
                      planPersons={plan?.persons ?? []}
                      onPlace={(drag, personId) => doPlace(drag, meal, personId)}
                      onDelete={() => deletePlanMeal(meal.id).then(setPlan)}
                      onRemoveFill={(fill) => deletePlanFill(fill.id).then(setPlan)}
                      onChangePersons={() => {
                        setEditingMeal(meal.id);
                        setPersonsSheet(true);
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
            );
          })}
        </div>
      </div>

      {addMealDay !== null && (
        <AddMealSheet
          plan={plan}
          onAdd={(mealName, personIds) =>
            addPlanMeal(week, addMealDay, mealName, personIds).then(setPlan)
          }
          onClose={() => setAddMealDay(null)}
        />
      )}
      {fillSheet && (
        <FillSheet
          key={fillSheet.drag.id + (fillSheet.mealId ?? "")}
          drag={fillSheet.drag}
          mealId={fillSheet.mealId}
          plan={plan}
          recipes={recipes}
          onSave={async (mealId, portions, prep) => {
            const updated = await addPlanFill(mealId, {
              recipeId: fillSheet.drag.kind === "recipe" ? fillSheet.drag.id : undefined,
              preparedId: fillSheet.drag.kind === "prepared" ? fillSheet.drag.id : undefined,
              portions,
              prepMultiplier: prep,
            });
            setPlan(updated);
            setFillSheet(null);
          }}
          onClose={() => setFillSheet(null)}
        />
      )}
      {personsSheet && (
        <PersonsSheet
          plan={plan}
          editingMealId={editingMeal}
          onClearEdit={() => setEditingMeal(null)}
          onAddPerson={(name) => addPlanPerson(name).then(setPlan)}
          onDeletePerson={(id) => deletePlanPerson(id).then(setPlan)}
          onToggleMealPerson={(mealId, personId) => togglePlanMealPerson(mealId, personId).then(setPlan)}
          onClose={() => {
            setEditingMeal(null);
            setPersonsSheet(false);
          }}
        />
      )}
      {preparedSheet && (
        <AddPreparedSheet
          onAdd={(name, portions) => addPreparedMeal(name, portions).then(setPlan)}
          onClose={() => setPreparedSheet(false)}
        />
      )}
      {weekListSheet && (
        <WeekListSheet
          week={week}
          entries={shoppingEntries}
          pushed={pushed}
          onRefresh={() => fetchPlanShoppingList(week).then(setShoppingEntries)}
          onPush={() => pushPlanShoppingList(week).then(() => setPushed(true))}
          onClose={() => setWeekListSheet(false)}
        />
      )}
    </div>
  );
}

interface MealCardProps {
  meal: PlanningMeal;
  planPersons: PlanPerson[];
  onPlace: (drag: DragPayload, personId: string | null) => void;
  onChangePersons: () => void;
  onDelete: () => void;
  onRemoveFill: (fill: PlanningFill) => void;
}

function FillRow({ fill, onRemoveFill }: { fill: PlanningFill; onRemoveFill: (fill: PlanningFill) => void }) {
  return (
    <div className="plan-fill">
      <span className="plan-fill-name">{fill.recipeTitle ?? fill.preparedName}</span>
      <span className="plan-fill-qty">
        {fill.portions} {fill.recipeId ? "p" : ""}
      </span>
      <button className="icon-btn" aria-label="Remove" onClick={() => onRemoveFill(fill)}>
        <IconX size={13} />
      </button>
    </div>
  );
}

function MealCard({
  meal,
  planPersons,
  onPlace,
  onChangePersons,
  onDelete,
  onRemoveFill,
}: MealCardProps) {
  // hover: "card" while dragging over the whole field, or the person id of
  // the half being targeted
  const [hover, setHover] = useState<string | null>(null);
  const halves = planPersons.length >= 2 ? planPersons : [];
  const shared = meal.fills.filter((f) => !f.personId);
  const tagged = meal.fills.filter((f) => f.personId);

  const drop = (e: DragEvent, personId: string | null) => {
    e.preventDefault();
    e.stopPropagation();
    setHover(null);
    const drag = parseDrag(e.dataTransfer.getData("text/plain"));
    if (drag) onPlace(drag, personId);
  };

  return (
    <div
      className={hover === "card" ? "plan-meal over" : "plan-meal"}
      onDragOver={(e) => {
        e.preventDefault();
        setHover((h) => h ?? "card");
      }}
      onDragLeave={() => setHover((h) => (h === "card" ? null : h))}
      onDrop={(e) => drop(e, null)}
    >
      <div className="plan-meal-head">
        <span className="plan-meal-name">{meal.meal}</span>
        <div className="plan-meal-actions">
          <button className="icon-btn" aria-label="Edit persons" onClick={onChangePersons}>
            <IconPlus size={14} />
          </button>
          {(meal.meal !== "Lunch" && meal.meal !== "Dinner") && (
            <button className="icon-btn" aria-label="Remove meal" onClick={onDelete}>
              <IconX size={14} />
            </button>
          )}
        </div>
      </div>
      {halves.length >= 2 && hover !== null ? (
        // during a drag the field splits into targeting zones: one strip for
        // everyone plus a half per person
        <>
          <div
            className={hover === "card" ? "plan-drop-all over" : "plan-drop-all"}
            onDragOver={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setHover("card");
            }}
            onDragLeave={(e) => {
              e.stopPropagation();
              setHover((h) => (h === "card" ? null : h));
            }}
            onDrop={(e) => drop(e, null)}
          >
            Everyone
          </div>
          <div className="plan-halves">
            {halves.map((p) => (
              <div
                key={p.id}
                className={hover === p.id ? "plan-half over" : "plan-half"}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setHover(p.id);
                }}
                onDragLeave={(e) => {
                  e.stopPropagation();
                  setHover((h) => (h === p.id ? null : h));
                }}
                onDrop={(e) => drop(e, p.id)}
              >
                <span className="plan-half-name">{p.name}</span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <>
          {/* one joint field per meal: a drop for everyone is a single
              full-width entry */}
          {shared.map((fill) => (
            <FillRow key={fill.id} fill={fill} onRemoveFill={onRemoveFill} />
          ))}
          {tagged.length > 0 && (
            <div className="plan-halves">
              {halves.map((p) => {
                const fills = tagged.filter((f) => f.personId === p.id);
                return fills.length > 0 ? (
                  <div key={p.id} className="plan-half">
                    <span className="plan-half-name">{p.name}</span>
                    {fills.map((fill) => (
                      <FillRow key={fill.id} fill={fill} onRemoveFill={onRemoveFill} />
                    ))}
                  </div>
                ) : null;
              })}
            </div>
          )}
          {meal.fills.length === 0 && (
            <div className="plan-meal-empty">Drop a recipe or prepared meal here</div>
          )}
        </>
      )}
    </div>
  );
}

function PreparedRow({
  prepared,
  onPlace,
  onDelete,
}: {
  prepared: PreparedMeal;
  onPlace: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className="plan-pick prepared"
      data-empty={prepared.available > 0 ? undefined : "1"}
      draggable={prepared.available > 0}
      onDragStart={(e) => e.dataTransfer.setData("text/plain", `prepared:${prepared.id}`)}
      onClick={() => prepared.available > 0 && onPlace()}
      title={prepared.available > 0 ? "Drop on a meal field to place directly — or tap for options" : "Fully placed"}
    >
      <div className="plan-prepared-name">{prepared.name}</div>
      <div className="plan-prepared-count">
        {prepared.available}/{prepared.portions} left
      </div>
      <button
        className="icon-btn"
        aria-label={`Delete ${prepared.name}`}
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
      >
        <IconX size={13} />
      </button>
    </div>
  );
}

function AddMealSheet({
  plan,
  onAdd,
  onClose,
}: {
  plan: WeekPlan | null;
  onAdd: (meal: string, personIds: string[]) => void;
  onClose: () => void;
}) {
  const [mealName, setMealName] = useState("Lunch");
  const [selected, setSelected] = useState<string[]>([]);
  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title">Add meal</h2>
      <p className="sheet-sub">Who eats this meal?</p>
      <div className="segmented">
        {MEAL_SUGGESTIONS.map((m) => (
          <button key={m} className={mealName === m ? "active" : ""} onClick={() => setMealName(m)}>
            {m}
          </button>
        ))}
      </div>
      <div className="chip-row" style={{ flexWrap: "wrap", paddingTop: 10 }}>
        {(plan?.persons ?? []).map((p) => (
          <button
            key={p.id}
            className={selected.includes(p.id) ? "chip active" : "chip"}
            onClick={() => setSelected((prev) => (prev.includes(p.id) ? prev.filter((x) => x !== p.id) : [...prev, p.id]))}
          >
            {p.name}
          </button>
        ))}
        {(plan?.persons.length ?? 0) === 0 && <span className="plan-empty">Add persons first.</span>}
      </div>
      <div className="sheet-actions">
        <button className="btn btn-primary" onClick={() => { onAdd(mealName, selected); onClose(); }} disabled={!(plan?.persons.length)}>
          Add meal
        </button>
      </div>
    </Sheet>
  );
}

function FillSheet({
  drag,
  mealId,
  plan,
  recipes,
  onSave,
  onClose,
}: {
  drag: DragPayload;
  mealId?: string;
  plan: WeekPlan | null;
  recipes: Recipe[];
  onSave: (mealId: string, portions: number, prep: number) => Promise<void>;
  onClose: () => void;
}) {
  const [target, setTarget] = useState<string | undefined>(mealId);
  const [portions, setPortions] = useState(1);
  const [prep, setPrep] = useState(0);
  const [saving, setSaving] = useState(false);

  const label =
    drag.kind === "recipe"
      ? recipes.find((r) => r.id === drag.id)?.title ?? "Recipe"
      : plan?.prepared.find((p) => p.id === drag.id)?.name ?? "Prepared meal";
  const prepared = drag.kind === "prepared" ? plan?.prepared.find((p) => p.id === drag.id) : undefined;
  const maxPortions = prepared ? Math.max(1, prepared.available) : 20;
  const allMealsEmpty = (plan?.meals.length ?? 0) === 0;

  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title">{label}</h2>
      <p className="sheet-sub">
        {drag.kind === "recipe"
          ? "Pick portions to eat and extra Food Prep portions (added to Prepared meals)"
          : "How many portions from this prepared batch?"}
      </p>
      {!target && (
        <>
          <p className="sheet-sub">Choose a meal field</p>
          {allMealsEmpty ? (
            <div className="plan-empty">No meals this week yet — add a meal to a day first.</div>
          ) : (
            plan!.meals.map((m) => (
              <button key={m.id} className="plan-meal-chip" onClick={() => setTarget(m.id)}>
                {DAY_NAMES[m.day]} · {m.meal}
                {m.persons.length > 0 && <span className="plan-meal-chip-persons"> · {m.persons.map((p) => p.name).join(", ")}</span>}
              </button>
            ))
          )}
        </>
      )}
      {target && (
        <>
          <StepperRow
            label="Portions"
            value={portions}
            unit="p"
            active
            min={1}
            onStep={(d) => setPortions((v) => Math.min(maxPortions, Math.max(1, v + d)))}
          />
          {drag.kind === "recipe" && (
            <StepperRow
              label="Food Prep"
              hint="extra portions prepared ahead"
              value={prep}
              unit="p"
              active={prep > 0}
              min={0}
              onStep={(d) => setPrep((v) => Math.max(0, v + d))}
            />
          )}
          <div className="sheet-actions">
            <button
              className="btn btn-primary"
              disabled={saving}
              onClick={async () => {
                setSaving(true);
                try {
                  await onSave(target, portions, prep);
                } finally {
                  setSaving(false);
                }
              }}
            >
              Add to plan
            </button>
          </div>
        </>
      )}
    </Sheet>
  );
}

function PersonsSheet({
  plan,
  editingMealId,
  onClearEdit,
  onAddPerson,
  onDeletePerson,
  onToggleMealPerson,
  onClose,
}: {
  plan: WeekPlan | null;
  editingMealId: string | null;
  onClearEdit: () => void;
  onAddPerson: (name: string) => void;
  onDeletePerson: (id: string) => void;
  onToggleMealPerson: (mealId: string, personId: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const meal = plan?.meals.find((m) => m.id === editingMealId) ?? null;
  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title">{meal ? `Who eats ${meal.meal}?` : "Persons"}</h2>
      <p className="sheet-sub">{meal ? "Tap to add or remove for this meal" : "Manage the people you plan for"}</p>
      {meal ? (
        <div className="chip-row" style={{ flexWrap: "wrap" }}>
          {plan!.persons.map((p) => {
            const on = meal.persons.some((x) => x.id === p.id);
            return (
              <button
                key={p.id}
                className={on ? "chip active" : "chip"}
                onClick={() => {
                  onToggleMealPerson(meal.id, p.id);
                  onClearEdit();
                }}
              >
                {p.name}
              </button>
            );
          })}
          {(plan?.persons.length ?? 0) === 0 && <span className="plan-empty">Add a person first.</span>}
        </div>
      ) : (
        <>
          <div className="chip-row" style={{ flexWrap: "wrap" }}>
            {(plan?.persons ?? []).map((p) => (
              <span key={p.id} className="chip">
                {p.name}
                <button className="chip-x" aria-label={`Remove ${p.name}`} onClick={() => onDeletePerson(p.id)}>
                  <IconX size={11} />
                </button>
              </span>
            ))}
          </div>
          <div className="inline-form">
            <input
              placeholder="Add person…"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && name.trim()) {
                  onAddPerson(name.trim());
                  setName("");
                }
              }}
            />
            <button
              className="btn btn-primary btn-sm"
              disabled={!name.trim()}
              onClick={() => {
                onAddPerson(name.trim());
                setName("");
              }}
            >
              Add
            </button>
          </div>
        </>
      )}
    </Sheet>
  );
}

function AddPreparedSheet({
  onAdd,
  onClose,
}: {
  onAdd: (name: string, portions: number) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [portions, setPortions] = useState(1);
  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title">Add prepared meal</h2>
      <p className="sheet-sub">Frozen meals or leftovers, ready to place on a day</p>
      <div className="inline-form">
        <input placeholder="Name (e.g. Frozen lasagna)" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <StepperRow label="Portions" value={portions} unit="p" active min={1} onStep={(d) => setPortions((v) => Math.max(1, v + d))} />
      <div className="sheet-actions">
        <button
          className="btn btn-primary"
          disabled={!name.trim()}
          onClick={() => {
            onAdd(name.trim(), portions);
            onClose();
          }}
        >
          Add
        </button>
      </div>
    </Sheet>
  );
}

function WeekListSheet({
  week,
  entries,
  pushed,
  onRefresh,
  onPush,
  onClose,
}: {
  week: string;
  entries: PlanShoppingEntry[] | null;
  pushed: boolean;
  onRefresh: () => void;
  onPush: () => void;
  onClose: () => void;
}) {
  useEffect(() => {
    onRefresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title">Week shopping list</h2>
      <p className="sheet-sub">Everything needed for the week of {week} (incl. food prep) that isn't in stock</p>
      {entries === null ? (
        <div className="plan-empty">Loading…</div>
      ) : entries.length === 0 ? (
        <div className="plan-empty">Nothing missing — the pantry covers this week.</div>
      ) : (
        <div className="plan-shop-list">
          {entries.map((e, i) => (
            <div key={i} className="plan-shop-entry">
              <span>{e.name}</span>
              <span className="plan-fill-qty">
                {Math.round(e.amount * 100) / 100} {e.unit}
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="sheet-actions">
        <button className="btn btn-primary" disabled={!entries?.length || pushed} onClick={onPush}>
          {pushed ? "Added" : "Add to shopping list"}
        </button>
      </div>
    </Sheet>
  );
}

/** Drag-and-drop recipe row inside a collapsible plan group. A green ring
 *  marks recipes whose every tracked ingredient is in pantry stock. */
function RecipePick({ recipe, inStock, onPick }: { recipe: Recipe; inStock: boolean; onPick: () => void }) {
  return (
    <div
      className={inStock ? "plan-pick in-stock" : "plan-pick"}
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", `recipe:${recipe.id}`)}
      onClick={onPick}
      title={inStock ? "All ingredients in stock" : "Drop on a meal field to place directly — or tap for options"}
    >
      {recipe.favorite && <IconStar size={13} filled className="plan-pick-star" />}
      <span className="plan-pick-name">{recipe.title}</span>
    </div>
  );
}
