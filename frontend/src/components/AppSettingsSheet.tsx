import type { Settings, SettingsPatch } from "../types";
import Sheet from "./Sheet";

interface AppSettingsSheetProps {
  settings: Settings;
  onSave: (patch: SettingsPatch) => void;
  onClose: () => void;
}

export default function AppSettingsSheet({ settings, onSave, onClose }: AppSettingsSheetProps) {
  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title">Settings</h2>
      <p className="sheet-sub">Optional features can be switched off here</p>

      <div className="setting-row">
        <div className="setting-text">
          <div className="setting-label">Food prep planning</div>
          <div className="setting-hint">
            Weekly meal plan with prepared meals and a week shopping list. Hides
            the Planning tab when off.
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={settings.planningEnabled}
          className={settings.planningEnabled ? "switch on" : "switch"}
          onClick={() => onSave({ planningEnabled: !settings.planningEnabled })}
        >
          <span className="switch-knob" />
        </button>
      </div>
    </Sheet>
  );
}
