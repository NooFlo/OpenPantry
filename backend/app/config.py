import json
import os

from . import repo

DEFAULT_LOCAL_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")
DEFAULT_CLOUD_BASE_URL = os.environ.get("CLOUD_BASE_URL", "https://api.mistral.ai/v1")
DEFAULT_CLOUD_MODEL = os.environ.get("CLOUD_MODEL", "mistral-small-latest")
TASKS = ("receipts", "recipes")


def get_model_choice(task: str) -> dict:
    raw = repo.get_setting(f"{task}_model")
    if raw:
        try:
            data = json.loads(raw)
            if data.get("provider") in ("local", "cloud") and data.get("model"):
                return {"provider": data["provider"], "model": data["model"]}
        except ValueError:
            pass
    return {"provider": "local", "model": DEFAULT_LOCAL_MODEL}


def set_model_choice(task: str, choice: dict):
    repo.set_setting(f"{task}_model", json.dumps({"provider": choice["provider"], "model": choice["model"]}))


def get_cloud_config() -> dict:
    return {
        "base_url": repo.get_setting("cloud_base_url", DEFAULT_CLOUD_BASE_URL),
        "api_key": repo.get_setting("cloud_api_key", ""),
        "model": repo.get_setting("cloud_model", DEFAULT_CLOUD_MODEL),
    }
