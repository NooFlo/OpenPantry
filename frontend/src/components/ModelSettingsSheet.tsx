import { useState } from "react";
import type { Settings, SettingsPatch } from "../types";
import Sheet from "./Sheet";

interface ModelSettingsSheetProps {
  task: "receipts" | "recipes";
  settings: Settings;
  localModels: string[];
  llmAvailable: boolean;
  onSave: (patch: SettingsPatch) => void;
  onClose: () => void;
}

export default function ModelSettingsSheet({ task, settings, localModels, llmAvailable, onSave, onClose }: ModelSettingsSheetProps) {
  const taskLabel = task === "recipes" ? "recipe import" : "receipt extraction";
  const current = task === "recipes" ? settings.recipesModel : settings.receiptsModel;

  const [provider, setProvider] = useState(current.provider);
  const [localModel, setLocalModel] = useState(current.provider === "local" ? current.model : "");
  const [cloudBaseUrl, setCloudBaseUrl] = useState(settings.cloudBaseUrl);
  const [cloudModel, setCloudModel] = useState(settings.cloudModel);
  const [apiKey, setApiKey] = useState("");

  const save = () => {
    const patch: SettingsPatch = {};
    if (provider === "local") {
      const model = localModel || localModels[0];
      if (!model) return;
      patch[task === "recipes" ? "recipesModel" : "receiptsModel"] = { provider: "local", model };
    } else {
      patch[task === "recipes" ? "recipesModel" : "receiptsModel"] = { provider: "cloud", model: cloudModel };
      patch.cloudBaseUrl = cloudBaseUrl;
      patch.cloudModel = cloudModel;
      if (apiKey) patch.cloudApiKey = apiKey;
    }
    onSave(patch);
    onClose();
  };

  return (
    <Sheet onClose={onClose}>
      <h2 className="sheet-title">Model settings</h2>
      <p className="sheet-sub">Model used for {taskLabel}</p>

      <div className="segmented">
        <button className={provider === "local" ? "active" : ""} onClick={() => setProvider("local")}>
          Local
        </button>
        <button className={provider === "cloud" ? "active" : ""} onClick={() => setProvider("cloud")}>
          Cloud
        </button>
      </div>

      {provider === "local" ? (
        localModels.length > 0 ? (
          <div className="chip-row" style={{ flexWrap: "wrap", paddingBottom: 10 }}>
            {localModels.map((name) => (
              <button
                key={name}
                className={name === localModel ? "chip active" : "chip"}
                onClick={() => setLocalModel(name)}
              >
                {name}
              </button>
            ))}
          </div>
        ) : (
          <p className="sheet-sub">
            {llmAvailable
              ? "No models installed. Run: ollama pull qwen2.5:3b-instruct"
              : "Ollama is not reachable. Start it or use a cloud model."}
          </p>
        )
      ) : (
        <>
          <input
            className="import-input"
            type="url"
            placeholder="API base URL"
            value={cloudBaseUrl}
            onChange={(e) => setCloudBaseUrl(e.target.value)}
          />
          <input
            className="import-input"
            type="text"
            placeholder="Cloud model name"
            value={cloudModel}
            onChange={(e) => setCloudModel(e.target.value)}
          />
          <input
            className="import-input"
            type="password"
            placeholder={settings.cloudKeySet ? "API key stored" : "API key"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <p className="sheet-sub">
            {settings.cloudKeySet
              ? "Leave the key empty to keep the stored one."
              : "Works with any OpenAI-compatible API (Mistral, OpenAI, Groq, …)."}
          </p>
        </>
      )}

      <div className="sheet-actions">
        <button className="btn btn-ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          onClick={save}
          disabled={provider === "local" && localModels.length === 0}
        >
          Save
        </button>
      </div>
    </Sheet>
  );
}
