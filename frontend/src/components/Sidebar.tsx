import type { Tab } from "../types";
import { IconHome, IconInventory, IconMoon, IconRecipe, IconSun } from "./Icons";

const sections: { id: Tab; label: string; icon: (props: { size?: number }) => JSX.Element }[] = [
  { id: "home", label: "Home", icon: IconHome },
  { id: "inventory", label: "Inventory", icon: IconInventory },
  { id: "recipes", label: "Recipes", icon: IconRecipe },
];

interface SidebarProps {
  active: Tab;
  onChange: (tab: Tab) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

export default function Sidebar({ active, onChange, theme, onToggleTheme }: SidebarProps) {
  return (
    <nav className="sidebar" aria-label="Primary">
      <div className="sidebar-brand">
        Open<span>Pantry</span>
      </div>
      <div className="sidebar-nav">
        {sections.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className={active === id ? "active" : ""}
            onClick={() => onChange(id)}
            aria-label={label}
            aria-current={active === id ? "page" : undefined}
          >
            <Icon size={22} />
            <span className="sidebar-label">{label}</span>
          </button>
        ))}
      </div>
      <div className="sidebar-footer">
        <button type="button" className="icon-btn" onClick={onToggleTheme} aria-label="Toggle theme">
          {theme === "dark" ? <IconSun size={19} /> : <IconMoon size={19} />}
        </button>
      </div>
    </nav>
  );
}
