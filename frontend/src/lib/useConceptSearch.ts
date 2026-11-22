import { useEffect, useState } from "react";
import { searchConcepts } from "../api";

export interface ConceptSuggestion {
  conceptId: string;
  label: string;
  /** The alias the search matched, when it wasn't the label itself. */
  alias: string | null;
}

/** Debounced catalog search for the food-tag picker: feed it the typed
 *  text, get back matching concepts (labels + aliases, both languages). */
export function useConceptSearch(query: string): ConceptSuggestion[] {
  const [results, setResults] = useState<ConceptSuggestion[]>([]);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      searchConcepts(q)
        .then((r) => live && setResults(r.results))
        .catch(() => live && setResults([]));
    }, 180);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [query]);

  return results;
}
