# OpenPantry USB scanner bridge (Rock5)

The keyboard-wedge side of the control-code system. This is the script that
runs on the Rock 5A as `barcode-bridge.service` — versioned here so the
`trash = consume` scheme (and future control-code changes) ship with the
repo instead of living only on the box.

## What a scan does

| Scanned | Effect |
|---|---|
| Product barcode (6–14 digits) | Restock or deduct one package, per the sticky mode (`/api/scan/purchase` / `/api/scan/barcode`); unknown products land in the app's review queue with their Open Food Facts data |
| `2000000000008` (**BOUGHT** sticker) | Sticky mode → BOUGHT: subsequent scans restock +1 package |
| `2000000000015` (**TRASH** sticker) | Back to the default mode: subsequent scans deduct one package — trash *is* consume, there is no third sticker |
| Custom label's QR / NFC URL (`…​/c/<item>`) | One package of that item consumed (`POST /api/scan/item`), in any mode |
| Anything else | Logged and ignored |

The mode is sticky and persisted across service restarts
(`/var/lib/barcode-bridge/mode`). The control-code digits are fetched from
the backend at startup (`GET /api/labels/control-codes` — the same source of
truth the sticker designs print from); the constants in the script are the
offline fallback, so a code change in `backend/app/labels.py` reaches the
Rock5 with a service restart.

Device handling is fully automatic and passive: wedge scanners enumerate as
HID keyboards and are discovered by their capabilities (digits + Enter),
one reader thread per device, hotplug watched every 2 s — no configuration,
and **no grab**, so a normal keyboard on the Rock5 keeps working.

## Install / update on the Rock5

```bash
sudo apt install python3-evdev
sudo cp scanner_bridge.py      /usr/local/bin/barcode-bridge.py
sudo cp scanner-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now barcode-bridge
journalctl -u barcode-bridge -f     # or: tail -f /var/log/barcode-bridge.log
```

The backend URL defaults to `http://localhost:8321`; override with
`Environment=PANTRY_URL=…` in the unit if OpenPantry ever moves.
