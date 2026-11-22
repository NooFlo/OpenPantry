import { useEffect, useRef, useState } from "react";

export interface AutocompleteSuggestion {
  key: string;
  /** Main text of the suggestion. */
  title: string;
  /** Secondary text, e.g. the matched alias for a food tag. */
  hint?: string;
}

interface AutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  suggestions: AutocompleteSuggestion[];
  /** Picking a suggestion from the dropdown. */
  onSelect: (suggestion: AutocompleteSuggestion) => void;
  /** Enter pressed with nothing highlighted — commit the typed text. */
  onEnter?: () => void;
  placeholder?: string;
  className?: string;
  inputStyle?: React.CSSProperties;
  disabled?: boolean;
}

/** Text input with a keyboard-navigable suggestion dropdown. Free text is
 *  always allowed: Enter commits what was typed via `onEnter` when no
 *  suggestion is highlighted. */
export default function Autocomplete({
  value,
  onChange,
  suggestions,
  onSelect,
  onEnter,
  placeholder,
  className,
  inputStyle,
  disabled,
}: AutocompleteProps) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const [edited, setEdited] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => setHighlighted(-1), [suggestions]);

  useEffect(() => {
    // close when clicking outside
    const onDocMouseDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, []);

  const showMenu = open && edited && value.trim() && suggestions.length > 0;

  const close = () => {
    setOpen(false);
    setHighlighted(-1);
  };

  const pick = (index: number) => {
    const suggestion = suggestions[index];
    if (!suggestion) return;
    onSelect(suggestion);
    setEdited(false);
    close();
  };

  return (
    <div ref={rootRef} style={{ position: "relative", flex: 1, minWidth: 0 }}>
      <input
        className={className}
        style={inputStyle}
        placeholder={placeholder}
        disabled={disabled}
        value={value}
        onChange={(e) => {
          setEdited(true);
          onChange(e.target.value);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && showMenu) {
            e.preventDefault();
            setHighlighted((h) => Math.min(h + 1, suggestions.length - 1));
          } else if (e.key === "ArrowUp" && showMenu) {
            e.preventDefault();
            setHighlighted((h) => Math.max(h - 1, 0));
          } else if (e.key === "Enter") {
            if (showMenu && highlighted >= 0) {
              e.preventDefault();
              pick(highlighted);
            } else {
              setEdited(false);
              close();
              onEnter?.();
            }
          } else if (e.key === "Escape") {
            close();
          }
        }}
      />
      {showMenu && (
        <div className="autocomplete-menu" role="listbox">
          {suggestions.map((s, index) => (
            <button
              key={s.key}
              type="button"
              role="option"
              aria-selected={index === highlighted}
              className={`autocomplete-item${index === highlighted ? " selected" : ""}`}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setHighlighted(index)}
              onClick={() => pick(index)}
            >
              <span className="autocomplete-title">{s.title}</span>
              {s.hint && <span className="autocomplete-hint">{s.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
