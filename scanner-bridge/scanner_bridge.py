#!/usr/bin/env python3
"""USB barcode scanner bridge for OpenPantry on the Rock 5A.

Watches for USB HID keyboard devices (1D and 2D wedge scanners enumerate as
keyboards), decodes keystrokes with a full US layout (shift, symbols,
backspace) and routes the completed scan:

  digits, 6-14      -> product scan in the current mode (see below)
  /c/<item-id> URL  -> item-label QR: consumes one package of that item
  control code      -> switch mode (sticky, persisted across restarts)

Scan modes (sticky until another control code is scanned):
  TRASH   2000000000015  -> consume mode: scans deduct one package (default)
  BOUGHT  2000000000008  -> bought mode: scans restock one package
TRASH *is* consume — scanning the TRASH sticker simply returns to the
default mode; there is no zero-and-reorder mode and no CONSUME sticker
anymore (the empty/consume codes of the Rock5's original bridge retired
with them; the control-code digits are fetched from the backend at startup
so future changes in labels.py need only a service restart).

Unknown barcodes are logged with their Open Food Facts data and land in the
app's review queue. Non-product content (arbitrary QR, random text) is logged
and ignored. Purely passive on the input device (no grabs), so a normal
keyboard still works.
"""
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request

import evdev

BASE = os.environ.get("PANTRY_URL", "http://localhost:8321")
SCAN_URLS = {
    "consume": BASE + "/api/scan/barcode",
    "bought": BASE + "/api/scan/purchase",
}
ITEM_SCAN_URL = BASE + "/api/scan/item"
LOOKUP_URL = BASE + "/api/barcode/lookup"
CODES_URL = BASE + "/api/labels/control-codes"
# Fallback control codes (GS1 in-store reserved range — no product collides);
# normally fetched from the backend at startup, the same single source of
# truth the sticker designs in the app print from.
CONTROL_CODES = {
    "2000000000008": "bought",
    "2000000000015": "consume",  # TRASH sticker: back to the deduct-one default
}
MODE_LABELS = {"consume": "CONSUME/TRASH (-1 package, default)",
               "bought": "BOUGHT (+1 package)"}
MODE_FILE = "/var/lib/barcode-bridge/mode"
SCAN_TIMEOUT = 0.5  # seconds of silence that resets the buffer
VALID_MODES = set(SCAN_URLS)
DIGITS_RE = re.compile(r"^[0-9]{6,14}$")
ITEM_URL_RE = re.compile(r"/c/([A-Za-z0-9._-]+)")

handlers = [logging.StreamHandler()]
try:  # journald captures stdout; the file log is a convenience on the Rock5
    handlers.append(logging.FileHandler("/var/log/barcode-bridge.log"))
except OSError:
    pass
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=handlers,
)
log = logging.getLogger("barcode-bridge")

_mode_lock = threading.Lock()
_mode = "consume"


def current_mode() -> str:
    with _mode_lock:
        return _mode


def set_mode(mode: str) -> None:
    global _mode
    with _mode_lock:
        _mode = mode
    try:
        os.makedirs(os.path.dirname(MODE_FILE), exist_ok=True)
        with open(MODE_FILE, "w") as fh:
            fh.write(mode)
    except OSError as e:
        log.warning("could not persist mode %s: %s", mode, e)
    log.info("MODE → %s", MODE_LABELS.get(mode, mode))


def fetch_control_codes() -> dict[str, str]:
    """Adopt the backend's control-code set (bought / trash keys map to modes:
    trash means 'back to consume' — scanning it deducts nothing itself)."""
    global CONTROL_CODES
    try:
        with urllib.request.urlopen(CODES_URL, timeout=10) as resp:
            codes = {entry["code"]: entry["key"] for entry in json.load(resp)}
        result = {}
        for code, key in codes.items():
            if key in ("bought", "trash"):
                # trash = consume: the sticker switches to the default mode
                result[code] = "bought" if key == "bought" else "consume"
        if result:
            if result != CONTROL_CODES:
                log.info("backend control codes override the fallback: %s", result)
            CONTROL_CODES = result
    except Exception as e:  # noqa: BLE001 — offline fallback keeps the bridge up
        log.warning("could not fetch control codes from %s (%s) — using fallback",
                    CODES_URL, e)
    return CONTROL_CODES


def _build_keymaps():
    base, shifted = {}, {}
    digits = "1234567890"
    symbols = "!@#$%^&*()"
    for index, digit in enumerate(digits):
        base[getattr(evdev.ecodes, "KEY_" + digit)] = digit
        shifted[getattr(evdev.ecodes, "KEY_" + digit)] = symbols[index]
    for letter in "abcdefghijklmnopqrstuvwxyz":
        code = getattr(evdev.ecodes, "KEY_" + letter.upper())
        base[code] = letter
        shifted[code] = letter.upper()
    pairs = {
        "MINUS": ("-", "_"), "EQUAL": ("=", "+"),
        "LEFTBRACE": ("[", "{"), "RIGHTBRACE": ("]", "}"),
        "BACKSLASH": ("\\", "|"), "SEMICOLON": (";", ":"),
        "APOSTROPHE": ("'", '"'), "GRAVE": ("`", "~"),
        "COMMA": (",", "<"), "DOT": (".", ">"), "SLASH": ("/", "?"),
    }
    for name, (plain, shifted_char) in pairs.items():
        code = getattr(evdev.ecodes, "KEY_" + name)
        base[code] = plain
        shifted[code] = shifted_char
    return base, shifted


KEY_BASE, KEY_SHIFT = _build_keymaps()
SHIFT_CODES = (evdev.ecodes.KEY_LEFTSHIFT, evdev.ecodes.KEY_RIGHTSHIFT)


def _post(url: str, payload: dict, timeout: int = 10):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            return resp.status, None
    except urllib.error.HTTPError as e:
        e.read()
        return e.code, None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def describe_product(barcode: str) -> str:
    """Open Food Facts enrichment for unknown barcodes (review queue fills in)."""
    body = json.dumps({"barcode": barcode}).encode()
    req = urllib.request.Request(
        LOOKUP_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except Exception as e:  # noqa: BLE001
        return "(lookup failed: %s)" % e
    if data.get("status") == "not_found":
        return "(no product found on Open Food Facts)"
    product = data.get("product") or {}
    desc = 'product="%s"' % product.get("name", "?")
    if product.get("brand"):
        desc += " brand=%s" % product["brand"]
    suggestions = [s.get("name") for s in data.get("suggestions") or []]
    if suggestions:
        desc += " maybe: %s" % "/".join(suggestions)
    return desc


def post_scancode(content: str) -> None:
    if content in CONTROL_CODES:
        set_mode(CONTROL_CODES[content])
        return
    mode = current_mode()
    if DIGITS_RE.match(content):
        status, err = _post(SCAN_URLS[mode], {"barcode": content})
        if status == 200:
            log.info("SCAN OK [%s] %s -> 200", mode, content)
        elif status == 404:
            log.info("SCAN UNKNOWN [%s] barcode=%s %s", mode, content,
                     describe_product(content))
        elif status is None:
            log.error("SCAN [%s] %s failed: %s", mode, content, err)
        else:
            log.error("SCAN [%s] %s failed: HTTP %s", mode, content, status)
        return
    match = ITEM_URL_RE.search(content)
    if match:
        status, err = _post(ITEM_SCAN_URL, {"item_id": match.group(1)})
        if status == 200:
            log.info("SCAN OK [item] /c/%s -> 200", match.group(1))
        elif status == 404:
            log.info("SCAN UNKNOWN [item] /c/%s (no such item)", match.group(1))
        else:
            log.error("SCAN [item] /c/%s failed: %s", match.group(1),
                      err or "HTTP %s" % status)
        return
    log.info("SCAN non-product content ignored: %r", content[:80])


def is_scanner_candidate(dev: evdev.InputDevice) -> bool:
    """A wedge scanner looks like a keyboard: digits and an Enter key."""
    try:
        caps = dev.capabilities(verbose=False)
        keys = set(caps.get(evdev.ecodes.EV_KEY, []))
        return (evdev.ecodes.KEY_ENTER in keys and
                evdev.ecodes.KEY_1 in keys and
                evdev.ecodes.KEY_0 in keys)
    except Exception:  # noqa: BLE001
        return False


def follow_device(dev: evdev.InputDevice) -> None:
    buffer: list[str] = []
    last_key_time = 0.0
    shift_down = False
    log.info("listening on %s (%s)", dev.path, dev.name)
    try:
        for event in dev.read_loop():
            if event.type != evdev.ecodes.EV_KEY:
                continue
            if event.code in SHIFT_CODES:
                shift_down = event.value != 0
                continue
            if event.value != 1:  # ignore autorepeat and releases
                continue
            now = time.monotonic()
            if now - last_key_time > SCAN_TIMEOUT:
                buffer = []
            last_key_time = now
            if event.code == evdev.ecodes.KEY_ENTER:
                if buffer:
                    post_scancode("".join(buffer))
                buffer = []
            elif event.code == evdev.ecodes.KEY_BACKSPACE:
                if buffer:
                    buffer.pop()
            elif event.code in KEY_BASE:
                buffer.append(KEY_SHIFT[event.code] if shift_down else KEY_BASE[event.code])
    except OSError:
        log.info("device %s went away", dev.path)


def main() -> None:
    global _mode
    try:
        with open(MODE_FILE) as fh:
            saved = fh.read().strip()
        if saved in VALID_MODES:
            _mode = saved
        elif saved:
            # a stale mode from an older bridge (e.g. "empty") -> default
            log.info("stored mode %r no longer exists, resetting to consume", saved)
    except OSError:
        pass
    fetch_control_codes()
    log.info("barcode bridge started, mode=%s, API=%s",
             MODE_LABELS.get(_mode, _mode), BASE)
    watched: dict[str, threading.Thread] = {}
    while True:
        for path, thread in list(watched.items()):
            if not thread.is_alive():
                log.info("releasing %s, reader stopped", path)
                del watched[path]
        for path in evdev.list_devices():
            if path in watched:
                continue
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            if is_scanner_candidate(dev):
                thread = threading.Thread(target=follow_device, args=(dev,),
                                           daemon=True)
                watched[path] = thread
                thread.start()
        time.sleep(2)


if __name__ == "__main__":
    main()
