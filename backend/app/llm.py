import difflib
import json
import os
import re
import time

import httpx

from . import telemetry

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
    choice = dict(choice or {"provider": "local", "model": OLLAMA_MODEL})
    if choice.get("provider") == "disabled":
        return None  # deterministic-only caller (catalog standardize)
    meta = {"provider": choice["provider"], "model": choice["model"], "prompt_chars": len(prompt)}
    start = time.perf_counter()
    try:
        if choice["provider"] == "cloud":
            result = _generate_json_cloud(prompt, choice["model"], cloud or {}, meta)
        else:
            result = _generate_json_local(prompt, choice["model"], meta)
    except Exception as exc:
        telemetry.record("llm", time.perf_counter() - start, ok=False, error=type(exc).__name__, **meta)
        raise
    telemetry.record("llm", time.perf_counter() - start, ok=result is not None, **meta)
    return result


def _generate_json_local(prompt: str, model: str, meta: dict) -> dict | list | None:
    try:
        response = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=120,
        )
        response.raise_for_status()
        body = response.json()
        meta.update(
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
            load_seconds=round(body.get("load_duration", 0) / 1e9, 2),
            prompt_eval_seconds=round(body.get("prompt_eval_duration", 0) / 1e9, 2),
            eval_seconds=round(body.get("eval_duration", 0) / 1e9, 2),
        )
        return json.loads(body["response"])
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def _generate_json_cloud(prompt: str, model: str, cloud: dict, meta: dict) -> dict | list | None:
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
        body = response.json()
        usage = body.get("usage") or {}
        meta.update(
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        return json.loads(body["choices"][0]["message"]["content"])
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        return None


CANON_RULES = (
    "For each ingredient name, output the raw grocery item name you would search for in a supermarket.\n"
    "REMOVE: quantities, packaging and measure words (dose, bund, Prise, Zehen, Stange, clove, bunch, stick, cup, handvoll), "
    "preparation words (gerieben, gehackt, gewürfelt, geschnitten, fein, mittel, klein, "
    "grated, chopped, sliced, diced, minced, crushed, washed, peeled, steamed, toasted), "
    "taste/ripeness words (reif, weich, hart, ripe, firm, fresh, frisch), "
    "and everything after a comma.\n"
    "NEVER split one ingredient into two. NEVER translate or change the language - "
    "German stays German, English stays English.\n"
    "DO NOT remove words that ARE the food: 'passierte Tomaten' and 'Kirschtomaten' "
    "stay exactly the same, 'Kartoffeln' and 'mehligkochende Kartoffeln' both "
    "become 'Kartoffeln'. "
    "Brand names, complete dish names and marinades stay unchanged.\n"
    "If you are not sure what to remove, copy the input exactly.\n"
    'Reply with JSON only: {"names": ["one output per input, same order"]}'
)


def canonicalize_names(
    names: list[str], choice: dict | None = None, cloud: dict | None = None
) -> dict[str, str]:
    """Map post-processed ingredient descriptions to raw grocery names.

    Guarded: batch size must match, empty/mistranslated outputs are rejected,
    anything unusable falls back to the input (deterministic stripping already
    ran before this is called).
    """
    unique = [n for n in dict.fromkeys(names) if n]
    if not unique:
        return {}
    payload = (
        CANON_RULES
        + "\n\nIngredient names:\n"
        + json.dumps(unique, ensure_ascii=False)
    )
    body = generate_json(payload, choice, cloud)
    if not isinstance(body, dict):
        return {}
    out = body.get("names")
    if not isinstance(out, list) or len(out) != len(unique):
        return {}
    mapping: dict[str, str] = {}
    for src, dst in zip(unique, out):
        if not isinstance(dst, str):
            continue
        dst = dst.strip().strip('"')
        if not dst or dst == src:
            continue
        # language-guard: reject outputs that drifted too far from the input
        # (e.g. "Knoblauch" -> "onion"); keep the input instead.
        if difflib.SequenceMatcher(None, src.lower(), dst.lower()).ratio() < 0.45:
            continue
        if len(dst) > len(src) + 30:
            continue
        mapping[src] = dst
    return mapping


ALIAS_RULES = (
    "The steps of a recipe mention these ingredients, sometimes with different words "
    "(pronouns like 'it', a marinade name, a synonym like 'garlic' for 'Knoblauch').\n"
    "For each ingredient, list the exact noun phrases (1-4 words) that actually appear in "
    "the step text and refer to it. Only include phrases you can find verbatim in the steps. "
    "Never invent phrases. Keep the language of the steps. No verbs, no sentences. "
    "Ingredient names already matching the steps need no alias.\n"
    'Reply with JSON only: {"aliases": {"<ingredient name>": ["phrase", ...], ...}} '
    "(omit ingredients with no alias)."
)


def step_aliases(
    names: list[str], steps: list[str], choice: dict | None = None, cloud: dict | None = None
) -> dict[str, list[str]]:
    """LLM proposes noun phrases from the step text for each ingredient —
    the deterministic linker then only accepts aliases found verbatim in
    the steps, so a hallucinated phrase never tags a wrong quantity."""
    names = [n for n in dict.fromkeys(names) if n]
    if not names or not any(s.strip() for s in steps):
        return {}
    payload = (
        ALIAS_RULES
        + "\n\nIngredients:\n"
        + json.dumps(names, ensure_ascii=False)
        + "\n\nSteps:\n"
        + json.dumps([s.strip() for s in steps], ensure_ascii=False)
    )
    body = generate_json(payload, choice, cloud)
    if not isinstance(body, dict) or not isinstance(body.get("aliases"), dict):
        return {}
    out: dict[str, list[str]] = {}
    for src, aliases in body["aliases"].items():
        if not isinstance(src, str) or src not in names or not isinstance(aliases, list):
            continue
        clean = []
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            alias = alias.strip().strip('"\',.').strip()
            # alias sanity: short noun-ish phrases only, never a quantity or sentence
            if not alias or len(alias) > 40 or len(alias.split()) > 4:
                continue
            if not re.search(r"[A-Za-zÄÖÜäöüß]", alias) or re.search(r"\d", alias):
                continue
            if alias.lower() == src.lower() or alias in clean:
                continue
            clean.append(alias)
        if clean:
            out[src] = clean[:5]
    return out
