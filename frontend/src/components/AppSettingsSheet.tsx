import { useEffect, useState } from "react";
import type { Settings, SettingsPatch } from "../types";
import Sheet from "./Sheet";

interface AppSettingsSheetProps {
  settings: Settings;
  onSave: (patch: SettingsPatch) => void;
  onClose: () => void;
}

export default function AppSettingsSheet({ settings, onSave, onClose }: AppSettingsSheetProps) {
  const [baseUrl, setBaseUrl] = useState("");

  useEffect(() => {
    setBaseUrl(settings.labelBaseUrl ?? "");
  }, [settings.labelBaseUrl]);

  const saveBaseUrl = () => {
    const trimmed = baseUrl.trim().replace(/\/+$/, "");
    if (trimmed !== (settings.labelBaseUrl ?? "")) onSave({ labelBaseUrl: trimmed });
  };

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

      <div className="setting-row" style={{ alignItems: "flex-start" }}>
        <div className="setting-text">
          <div className="setting-label">Label &amp; QR base URL</div>
          <div className="setting-hint">
            The address baked into label QRs and NFC links — phones must be able
            to open it (e.g. <code>http://192.168.178.96:8321</code>). Leave empty
            and the server auto-detects its LAN IP. Set it explicitly when
            OpenPantry runs in Docker (auto-detect would return the container IP).
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            <input
              className="import-input"
              style={{ marginBottom: 0, fontFamily: "monospace" }}
              placeholder="auto-detect — leave empty"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              onBlur={saveBaseUrl}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveBaseUrl();
              }}
            />
          </div>
        </div>
      </div>
    </Sheet>
  );
}
