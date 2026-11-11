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


def generate_json(prompt: str) -> dict | list | None:
    try:
        response = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=120,
        )
        response.raise_for_status()
        return json.loads(response.json()["response"])
    except (httpx.HTTPError, ValueError, KeyError):
        return None
