import { IconMoon, IconSun } from "./Icons";

interface ThemeToggleProps {
  theme: "light" | "dark";
  onToggle: () => void;
}

export default function ThemeToggle({ theme, onToggle }: ThemeToggleProps) {
  return (
    <button className="icon-btn" onClick={onToggle} aria-label="Toggle theme">
      {theme === "dark" ? <IconSun size={19} /> : <IconMoon size={19} />}
    </button>
  );
}
