import json
import logging
import os

import httpx

from . import repo

log = logging.getLogger("openpantry.ha")

DEFAULT_HA_URL = os.environ.get("HA_URL", "")
DEFAULT_HA_TOKEN = os.environ.get("HA_TOKEN", "")
DEFAULT_HA_ENTITY = os.environ.get("HA_ENTITY", "todo.shopping_list")

_TIMEOUT = 10.0


def get_config() -> dict:
    return {
        "base_url": (repo.get_setting("ha_url", DEFAULT_HA_URL) or "").strip().rstrip("/"),
        "token": (repo.get_setting("ha_token", DEFAULT_HA_TOKEN) or "").strip(),
        "entity_id": (repo.get_setting("ha_entity", DEFAULT_HA_ENTITY) or DEFAULT_HA_ENTITY).strip(),
    }


def enabled() -> bool:
    cfg = get_config()
    return bool(cfg["base_url"]) and bool(cfg["token"])


def _item_text(entry: dict) -> str:
    name = entry["name"]
    amount = entry.get("amount")
    if not amount:
        return name
    pretty = f"{amount:.2f}".rstrip("0").rstrip(".")
    unit = (entry.get("unit") or "").strip()
    return f"{name} ({pretty} {unit})" if unit else f"{name} ({pretty})"


def _pushed_texts() -> set[str]:
    raw = repo.get_setting("ha_pushed")
    if not raw:
        return set()
    try:
        data = json.loads(raw)
        return {str(t) for t in data} if isinstance(data, list) else set()
    except ValueError:
        return set()


def _call(cfg: dict, service: str, payload: dict) -> bool:
    url = f"{cfg['base_url']}/api/services/todo/{service}"
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {cfg['token']}"},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.error("Home Assistant todo/%s call failed: %s", service, exc)
        return False


def sync(desired: list[dict] | None = None) -> bool:
    """Reconcile the Home Assistant to-do list with the pantry shopping list.

    Only items this module pushed before are ever removed, so hand-added
    entries in Home Assistant are left alone.
    """
    if not enabled():
        return False
    cfg = get_config()
    if desired is None:
        desired = repo.list_shopping_list()
    wanted = {_item_text(entry) for entry in desired}
    pushed = _pushed_texts()
    entity = {"entity_id": cfg["entity_id"]}
    ok = True
    for text in sorted(pushed - wanted):
        if not _call(cfg, "remove_item", {"item": text, **entity}):
            ok = False
    for text in sorted(wanted - pushed):
        if not _call(cfg, "add_item", {"item": text, **entity}):
            ok = False
    if ok:
        repo.set_setting("ha_pushed", json.dumps(sorted(wanted)))
    else:
        log.warning("Home Assistant shopping list out of sync")
    return ok
