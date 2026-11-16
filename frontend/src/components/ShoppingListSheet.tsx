import { useState } from "react";
import type { Settings, SettingsPatch, ShoppingListEntry } from "../types";
import Sheet from "./Sheet";

interface ShoppingListSheetProps {
  entries: ShoppingListEntry[];
  settings: Settings;
  onRemove: (itemId: string) => void;
  onSaveSettings: (patch: SettingsPatch) => void;
  onPush: () => Promise<{ pushed: boolean }>;
  onClose: () => void;
}

export default function ShoppingListSheet({
  entries,
  settings,
  onRemove,
  onSaveSettings,
  onPush,
  onClose,
}: ShoppingListSheetProps) {
  const [haUrl, setHaUrl] = useState(settings.haUrl ?? "");
  const [haToken, setHaToken] = useState("");
  const [pushing, setPushing] = useState(false);
  const [pushResult, setPushResult] = useState<string | null>(null);

  const push = async () => {
    setPushing(true);
    try {
      const result = await onPush();
      setPushResult(result?.pushed ? "Pushed to Home Assistant." : "Push failed, check the backend logs.");
    } catch {
      setPushResult("Home Assistant not reachable.");
    } finally {
      setPushing(false);
    }
  };

  const saveHaSettings = () => {
    const patch: SettingsPatch = { haUrl, haEntity: settings.haEntity };
    if (haToken) patch.haToken = haToken;
    setHaToken("");
    onSaveSettings(patch);
  };

  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title">Shopping list</h2>
      <p className="sheet-sub">
        {entries.length === 0 ? "The list is empty." : `${entries.length} item${entries.length === 1 ? "" : "s"} to buy.`}
      </p>

      {entries.map((entry) => (
        <div key={entry.itemId} className="sl-row">
          <div className="info">
            <div className="item-name">{entry.name}</div>
          </div>
          <span className="qty">
            +{entry.amount} {entry.unit}
          </span>
          <button className="icon-btn" aria-label={`Remove ${entry.name}`} onClick={() => onRemove(entry.itemId)}>
            ×
          </button>
        </div>
      ))}

      <h3 className="sheet-h3">Home Assistant</h3>
      <p className="sheet-sub">
        {settings.haKeySet
          ? "Changes to this list are pushed to the Home Assistant to-do list automatically."
          : "Add your Home Assistant URL and a long-lived access token to sync this list."}
      </p>
      {!settings.haKeySet && (
        <>
          <input
            className="import-input"
            type="url"
            placeholder="Home Assistant URL (e.g. http://homeassistant.local:8123)"
            value={haUrl}
            onChange={(e) => setHaUrl(e.target.value)}
          />
          <input
            className="import-input"
            type="password"
            placeholder="Long-lived access token"
            value={haToken}
            onChange={(e) => setHaToken(e.target.value)}
          />
        </>
      )}
      {pushResult && <p className="sheet-sub">{pushResult}</p>}
      <div className="sheet-actions">
        {!settings.haKeySet && (
          <button className="btn btn-ghost" disabled={!haUrl.trim() || !haToken.trim() || pushing} onClick={saveHaSettings}>
            Save
          </button>
        )}
        <button className="btn btn-primary" disabled={pushing} onClick={push}>
          {pushing ? "Pushing…" : "Push now"}
        </button>
      </div>
    </Sheet>
  );
}
