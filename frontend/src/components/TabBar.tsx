import type { Tab } from "../types";
import { IconHome, IconInventory, IconPlan, IconRecipe } from "./Icons";

const allTabs: { id: Tab; label: string; icon: (props: { size?: number }) => JSX.Element }[] = [
  { id: "home", label: "Home", icon: IconHome },
  { id: "inventory", label: "Inventory", icon: IconInventory },
  { id: "recipes", label: "Recipes", icon: IconRecipe },
  { id: "plan", label: "Plan", icon: IconPlan },
];

interface TabBarProps {
  active: Tab;
  onChange: (tab: Tab) => void;
  planningEnabled: boolean;
}

export default function TabBar({ active, onChange, planningEnabled }: TabBarProps) {
  const tabs = planningEnabled ? allTabs : allTabs.filter((t) => t.id !== "plan");
  return (
    <nav className="tab-bar">
      {tabs.map(({ id, label, icon: Icon }) => (
        <button key={id} className={active === id ? "active" : ""} onClick={() => onChange(id)}>
          <Icon size={22} />
          {label}
        </button>
      ))}
    </nav>
  );
}
