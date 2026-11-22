# OpenPantry USB scanner bridge (Rock5)

The keyboard-wedge side of the control-code system. USB barcode scanners
type their scans like a keyboard + Enter; this daemon grabs the scanner's
input device, buffers each scan and routes it to the OpenPantry backend.

It used to live only on the Rock5 — it is versioned here now so the
`trash = consume` scheme (and any future control-code change) ships with
the repo.

## What a scan does

| Scanned | Route | Effect |
|---|---|---|
| Product barcode (6–14 digits) | `POST /api/scan/barcode` or `/api/scan/purchase` (per mode) | deduct / restock one package |
| Control code `2000000000008` (**BOUGHT** sticker) | – (mode switch) | subsequent scans restock +1 package |
| Control code `2000000000015` (**TRASH** sticker) | – (mode switch) | back to the default: scans deduct one package — trash *is* consume, no separate CONSUME sticker |
| Custom label's QR / NFC URL (`…/c/<item>`) | `POST /api/scan/item` | one package of that item consumed |

The mode is sticky until the next control code. Unknown barcodes answer
404 in any mode and land in the review popup (the backend caches the
Open Food Facts product either way). The control-code digits are fetched
from the backend at startup (`GET /api/labels/control-codes`) — the same
source the sticker designs print from — so a code change in
`backend/app/labels.py` reaches the bridge with a service restart.

## Install on the Rock5

```bash
# 1. dependency (Debian/Armbian)
sudo apt install python3-evdev        # or: pip3 install --break-system-packages evdev

# 2. find the scanner's input device (scan something and watch which device buzzes)
python3 /opt/openpantry/scanner-bridge/scanner_bridge.py --list-devices

# 3. dry run without systemd (scans also reach your focused window — Ctrl+C to quit)
python3 scanner_bridge.py --url http://localhost:8321 \
    --device /dev/input/by-id/usb-XXXX-event-kbd --no-grab

# 4. install the service (edit --url and --device inside the unit first)
sudo cp scanner-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scanner-bridge
journalctl -u scanner-bridge -f
```

No hardware at hand (or deploying from your Mac)? The routing can be
verified anywhere:

```bash
python3 scanner_bridge.py --selftest    # no evdev needed, stub backend
```

## Notes

- The device is `grab()`bed so scanned digits don't also land in whatever
  window has focus. Pass `--no-grab` while testing.
- Multiple scanners: repeat `--device` (or `--device-name <substring>`).
- The scanner must be configured with **Enter/HID-Keyboard suffix** (the
  factory default for most wedge scanners).
- If the bridge and the backend disagree about control codes, the fetched
  backend set wins; the constants in the script are only an offline
  fallback.
