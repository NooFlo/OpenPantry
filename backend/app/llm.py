import json
import os

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")


def available() -> bool:
    try:
        response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def local_models() -> list[str]:
    try:
        response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        return []


def generate_json(prompt: str, choice: dict | None = None, cloud: dict | None = None) -> dict | list | None:
    choice = choice or {"provider": "local", "model": OLLAMA_MODEL}
    if choice["provider"] == "cloud":
        return _generate_json_cloud(prompt, choice["model"], cloud or {})
    return _generate_json_local(prompt, choice["model"])


def _generate_json_local(prompt: str, model: str) -> dict | list | None:
    try:
        response = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=120,
        )
        response.raise_for_status()
        return json.loads(response.json()["response"])
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def _generate_json_cloud(prompt: str, model: str, cloud: dict) -> dict | list | None:
    if not cloud.get("api_key"):
        return None
    try:
        response = httpx.post(
            f"{cloud['base_url'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {cloud['api_key']}"},
            json={
                "model": model or cloud.get("model"),
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        response.raise_for_status()
        return json.loads(response.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        return None
