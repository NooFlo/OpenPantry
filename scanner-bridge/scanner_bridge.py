#!/usr/bin/env python3
"""OpenPantry USB scanner bridge — the Rock5 side of the control-code system.

Keyboard-wedge USB barcode scanners type their scans like a keyboard and
press Enter. This daemon grabs the scanner's input device, buffers each
scan into a line and routes it to the OpenPantry backend:

- A product barcode (6–14 digits) goes to the endpoint of the active mode:
    consume (default) → POST /api/scan/barcode   — deducts one package
    bought            → POST /api/scan/purchase  — restocks one package
  BOUGHT-mode scans of unknown products auto-create the item from its
  Open Food Facts data; unknown barcodes land in the review popup (the
  backend answers 404 and caches the product for the queue) — in any mode.
- A control-code sticker switches the sticky mode:
    BOUGHT 2000000000008 → mode "bought"
    TRASH 2000000000015  → mode "consume" (trash *is* consume: scanning
    one product deducts one package — the same as the default mode, which
    is why there is no separate CONSUME sticker anymore)
- A custom label's QR (or an NFC tag URL typed by a wedge-friendly reader)
  contains the item's consume landing page, `<origin>/c/<item-id>` — the
  bridge extracts the id and consumes one package via POST /api/scan/item.

The mode is sticky until the next control code. Every scan is logged to
the journal (systemd) / stdout. The control-code digits are fetched from
the backend at startup (`GET /api/labels/control-codes` — the same single
source of truth the sticker designs print from); the constants below are
only the offline fallback.

Usage:
  scanner_bridge.py --url http://pantry.local:8321 \
      --device /dev/input/by-id/usb-<scanner>-event-kbd
  scanner_bridge.py --list-devices
  scanner_bridge.py --selftest        # no hardware: routing table dry run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.error
import urllib.request

try:
    import evdev
    from evdev import ecodes, list_devices
except ImportError:  # evdev needs Linux — the selftest still runs anywhere
    evdev = None
    ecodes = None

    def list_devices():  # type: ignore[misc]
        return []


def _ensure_evdev():
    if evdev is None:
        sys.exit("python-evdev is required on this machine: "
                 "`sudo apt install python3-evdev` or `pip install evdev`")

# Fallback control codes (GS1 in-store reserved range, no product collides).
# Normally fetched from the backend at startup so a future code change in
# labels.py propagates to the bridge with a restart — no code edit here.
FALLBACK_CONTROL_CODES = {
    "bought": "2000000000008",
    "trash": "2000000000015",
}
BARCODE_RE = re.compile(r"^\d{6,14}$")
# A custom-label QR / NFC tag carries the consume landing page: <origin>/c/<id>
ITEM_URL_RE = re.compile(r"(?:https?://[^/\s]+)?/c/([A-Za-z0-9._~-]+)", re.IGNORECASE)

# Control-code keys the backend serves; the sticky scan *modes* are
# "consume" (the default) and "bought" — TRASH switches back to consume.
CONTROL_KEYS = ("bought", "trash")
MODES = ("consume", "bought")

log = logging.getLogger("scanner-bridge")


# ---------------------------------------------------------------- backend API


class Pantry:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict | None = None):
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=body, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as err:
            try:
                detail = err.read().decode(errors="replace").strip()
            except Exception:  # noqa: BLE001
                detail = ""
            return err.code, detail
        except urllib.error.URLError as err:
            return 0, str(err)

    def health(self):
        return self._request("GET", "/api/health")

    def control_codes(self):
        status, body = self._request("GET", "/api/labels/control-codes")
        if status == 200 and isinstance(body, list):
            return {entry["key"]: entry["code"] for entry in body
                    if isinstance(entry, dict) and entry.get("key") in CONTROL_KEYS}
        return None

    def scan(self, endpoint: str, payload: dict):
        return self._request("POST", f"/api/scan/{endpoint}", payload)


# ---------------------------------------------------------------- routing


class Router:
    """Decides what a scanned line means. One instance holds the sticky mode."""

    def __init__(self, pantry: Pantry, control_codes: dict[str, str]):
        self.pantry = pantry
        self.control_codes = control_codes
        self.mode = "consume"
        self.bought_code = control_codes.get("bought", FALLBACK_CONTROL_CODES["bought"])
        self.trash_code = control_codes.get("trash", FALLBACK_CONTROL_CODES["trash"])

    def handle_line(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        match = ITEM_URL_RE.search(text)
        if match:
            item_id = match.group(1).rstrip("/.-")
            status, body = self.pantry.scan("item", {"item_id": item_id})
            self._report(status, body, f"label QR — item {item_id} — one package consumed")
            return
        if text == self.bought_code:
            self.mode = "bought"
            log.info("control code BOUGHT scanned — mode: subsequent scans restock +1 package")
            return
        if text == self.trash_code:
            self.mode = "consume"
            log.info("control code TRASH scanned — mode: back to consume "
                     "(subsequent scans deduct one package)")
            return
        if BARCODE_RE.match(text):
            if self.mode == "bought":
                status, body = self.pantry.scan("purchase", {"barcode": text})
                self._report(status, body, f"bought-mode scan {text} — restocked one package")
            else:
                status, body = self.pantry.scan("barcode", {"barcode": text})
                self._report(status, body, f"consume-mode scan {text} — deducted one package")
            return
        log.warning("ignored scan (neither barcode, control code nor item URL): %r", text)

    def _report(self, status: int, body, success_note: str) -> None:
        if status == 200:
            name = ""
            if isinstance(body, dict):
                name = f" {body.get('name', '')}".rstrip()
            log.info("OK%s — %s", name, success_note)
        elif status == 404:
            log.info("unknown barcode — landed in the OpenPantry review queue (%s)", body)
        elif status == 500:
            log.error("backend error on scan: %s", body)
        else:
            log.error("scan failed (HTTP %s): %s", status, body)


# ---------------------------------------------------------------- HID reading


# Unshifted and shifted characters per evdev key code — enough for EAN/QR
# wedges (digits, letters and the few symbols a URL needs). Only built where
# evdev exists (Linux); the keymap globals stay empty elsewhere and
# LineReader is never used without a real device.
_KEY_CHAR: dict[int, str] = {}
_KEY_CHAR_SHIFT: dict[int, str] = {}
_SHIFT_KEYS: set[int] = set()
_ENTER_KEYS: set[int] = set()
if ecodes is not None:
    _KEY_CHAR.update({
        ecodes.KEY_1: "1", ecodes.KEY_2: "2", ecodes.KEY_3: "3", ecodes.KEY_4: "4",
        ecodes.KEY_5: "5", ecodes.KEY_6: "6", ecodes.KEY_7: "7", ecodes.KEY_8: "8",
        ecodes.KEY_9: "9", ecodes.KEY_0: "0", ecodes.KEY_MINUS: "-",
        ecodes.KEY_EQUAL: "=", ecodes.KEY_SPACE: " ", ecodes.KEY_DOT: ".",
        ecodes.KEY_COMMA: ",", ecodes.KEY_SLASH: "/",
        ecodes.KEY_SEMICOLON: ";", ecodes.KEY_APOSTROPHE: "'",
    })
    _KEY_CHAR_SHIFT.update({
        ecodes.KEY_1: "!", ecodes.KEY_2: "@", ecodes.KEY_3: "#", ecodes.KEY_4: "$",
        ecodes.KEY_5: "%", ecodes.KEY_6: "^", ecodes.KEY_7: "&", ecodes.KEY_8: "*",
        ecodes.KEY_9: "(", ecodes.KEY_0: ")", ecodes.KEY_MINUS: "_",
        ecodes.KEY_EQUAL: "+", ecodes.KEY_SPACE: " ", ecodes.KEY_DOT: ">",
        ecodes.KEY_COMMA: "<", ecodes.KEY_SLASH: "?",
        ecodes.KEY_SEMICOLON: ":", ecodes.KEY_APOSTROPHE: "\"",
    })
    for _code in range(ecodes.KEY_A, ecodes.KEY_Z + 1):
        _KEY_CHAR[_code] = chr(ord("a") + _code - ecodes.KEY_A)
        _KEY_CHAR_SHIFT[_code] = chr(ord("A") + _code - ecodes.KEY_A)
    _KEY_CHAR.update({
        ecodes.KEY_KP0: "0", ecodes.KEY_KP1: "1", ecodes.KEY_KP2: "2",
        ecodes.KEY_KP3: "3", ecodes.KEY_KP4: "4", ecodes.KEY_KP5: "5",
        ecodes.KEY_KP6: "6", ecodes.KEY_KP7: "7", ecodes.KEY_KP8: "8",
        ecodes.KEY_KP9: "9",
    })
    _SHIFT_KEYS.update((ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT))
    _ENTER_KEYS.update((ecodes.KEY_ENTER, ecodes.KEY_KPENTER))


class LineReader:
    """Buffers one wedge scan (Enter-terminated) from an input device."""

    def __init__(self, device, grab: bool = True):
        self.device = device
        self.buffer: list[str] = []
        self.shift = False
        if grab:
            try:
                device.grab()  # keep the typed digits out of the shell/VT
            except OSError as err:
                log.warning("could not grab %s (%s) — scans will also reach the focused window",
                            device.path, err)

    def fileno(self) -> int:
        return self.device.fd

    def read_line(self) -> str | None:
        """Process available events; return a finished line when Enter arrives."""
        for event in self.device.read():
            if event.type != ecodes.EV_KEY:
                continue
            key, value = event.code, event.value  # 1 = press, 0 = release
            if key in _SHIFT_KEYS:
                self.shift = value == 1
            elif value == 1 and key in _ENTER_KEYS:
                line = "".join(self.buffer)
                self.buffer.clear()
                return line
            elif value == 1 and not self.shift and key in _KEY_CHAR:
                self.buffer.append(_KEY_CHAR[key])
            elif value == 1 and self.shift and key in _KEY_CHAR_SHIFT:
                self.buffer.append(_KEY_CHAR_SHIFT[key])
        return None


# ---------------------------------------------------------------- entry point


def pick_device(name: str):
    _ensure_evdev()
    for path in list_devices():
        try:
            device = evdev.InputDevice(path)
        except OSError:
            continue
        if name in device.name or name in path:
            return device
    return None


def open_devices(paths: list[str], grab: bool) -> list[LineReader]:
    _ensure_evdev()
    readers = []
    for path in paths:
        try:
            readers.append(LineReader(evdev.InputDevice(path), grab=grab))
            log.info("listening on %s", path)
        except OSError as err:
            log.error("cannot open %s: %s", path, err)
    return readers


def selftest(pantry: Pantry) -> int:
    """Routing dry run without hardware: exercises every branch of handle_line
    against a stub backend, so a deployment can be verified on any machine."""
    calls = []

    class Stub:
        def scan(self, endpoint, payload):
            calls.append((endpoint, payload))
            return 200, {"name": "Salz"}

        def control_codes(self):
            return None

    router = Router.__new__(Router)  # type: ignore[arg-type]
    router.pantry = Stub()  # type: ignore[assignment]
    router.mode = "consume"
    router.bought_code = FALLBACK_CONTROL_CODES["bought"]
    router.trash_code = FALLBACK_CONTROL_CODES["trash"]
    router.handle_line("2000000000008")           # → mode bought
    router.handle_line("4012345678902")          # → /api/scan/purchase
    router.handle_line("2000000000015")          # → back to consume
    router.handle_line("4012345678902")          # → /api/scan/barcode
    router.handle_line("http://192.168.178.96:8321/c/salz")  # → /api/scan/item
    router.handle_line("/c/milch")               # relative label URL
    router.handle_line("12-AB-not-a-barcode")    # → ignored (no call)
    expected = [
        ("purchase", {"barcode": "4012345678902"}),
        ("barcode", {"barcode": "4012345678902"}),
        ("item", {"item_id": "salz"}),
        ("item", {"item_id": "milch"}),
    ]
    ok = calls == expected
    for endpoint, payload in calls:
        print(f"POST /api/scan/{endpoint} {payload}")
    print(f"{'PASS' if ok else 'FAIL'} — {len(calls)} API calls in dry run")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8321",
                        help="OpenPantry base URL (default: http://localhost:8321)")
    parser.add_argument("--device", action="append", default=[],
                        help="input device path(s) of the scanner — repeatable "
                             "(see --list-devices)")
    parser.add_argument("--device-name", action="append", default=[],
                        help="scanner input device(s) chosen by (sub)string of "
                             "their name or path — repeatable")
    parser.add_argument("--no-grab", action="store_true",
                        help="do not grab the device (scans also reach the "
                             "focused window — useful for testing)")
    parser.add_argument("--list-devices", action="store_true",
                        help="list input devices seen by evdev and exit")
    parser.add_argument("--selftest", action="store_true",
                        help="routing dry run without hardware, then exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.selftest:
        return selftest(Pantry(args.url))

    if args.list_devices:
        _ensure_evdev()
        for path in list_devices():
            try:
                print(f"{path}  {evdev.InputDevice(path).name}")
            except OSError:
                print(f"{path}  (unreadable)")
        return 0

    devices: list[str] = list(args.device)
    for needle in args.device_name:
        found = pick_device(needle)
        if found is None:
            log.error("no input device matches %r", needle)
            return 1
        devices.append(found.path)

    if not devices:
        log.error("no --device given (find yours with --list-devices)")
        return 1

    pantry = Pantry(args.url)
    status, _ = pantry.health()
    if status != 200:
        log.warning("backend at %s did not answer /api/health (HTTP %s) — "
                    "starting anyway, scans will retry", args.url, status)
    else:
        log.info("backend online at %s", args.url)

    codes = pantry.control_codes()
    if codes and codes != FALLBACK_CONTROL_CODES:
        log.info("backend control codes override the fallback: %s", codes)
    control_codes = codes or FALLBACK_CONTROL_CODES
    router = Router(pantry, control_codes)

    import select

    readers = open_devices(devices, grab=not args.no_grab)
    if not readers:
        return 1
    log.info("ready — mode: %s (control codes BOUGHT %s / TRASH %s)",
             router.mode, router.bought_code, router.trash_code)
    while True:
        try:
            _, _, _ = select.select(readers, [], [])
        except KeyboardInterrupt:
            return 0
        for reader in readers:
            line = reader.read_line()
            while line is not None:
                router.handle_line(line)
                line = reader.read_line()


if __name__ == "__main__":
    sys.exit(main())
