import type { Tab } from "../types";
import { IconHome, IconInventory, IconRecipe } from "./Icons";

const tabs: { id: Tab; label: string; icon: (props: { size?: number }) => JSX.Element }[] = [
  { id: "home", label: "Home", icon: IconHome },
  { id: "inventory", label: "Inventory", icon: IconInventory },
  { id: "recipes", label: "Recipes", icon: IconRecipe },
];

interface TabBarProps {
  active: Tab;
  onChange: (tab: Tab) => void;
}

export default function TabBar({ active, onChange }: TabBarProps) {
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
