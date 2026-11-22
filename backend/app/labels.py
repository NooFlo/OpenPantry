"""Custom label rendering and Epson Label Editor mobile (.lemd) export.

Mirrors the pipeline of LabelGenerator (github.com/NooFlo/LabelGenerator):
per-item drag-and-drop label designs made of absolutely positioned boxes
(mm coordinates, per-element point-based font sizes) rendered to PNG, then
batches stitched into a continuous .lemd strip with dashed cut marks. The
.lemd file is imported into the Epson Label Editor mobile app, which
prints it over Bluetooth.

Geometry constants follow LabelGenerator's lemd-generator exactly:
12 mm tape → 9.878 mm printable (top offset 0.92 mm),
24 mm tape → 18.1 mm printable (top offset 2.95 mm), 4 mm cut margin,
1 mm side margins, threshold dithering, payload version 1.2.0.
"""

import base64
import io
import json
import re

import barcode as barcode_lib
import qrcode
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw, ImageFont
from qrcode.image.pil import PilImage

# Scanner control codes: sticky modes switched by scanning one of these
# EAN-13 stickers. GS1 in-store reserved range (20xxxxxxxxxx — no product
# collides). Two codes only: BOUGHT switches to restock mode, TRASH switches
# back to the default consume mode (deduct one package) — TRASH *is* consume,
# which is why there is no third sticker.
CONTROL_CODES = {
    "bought": {"code": "2000000000008", "label": "BOUGHT",
               "hint": "Scanned items restock (+1 package)"},
    "trash": {"code": "2000000000015", "label": "TRASH",
              "hint": "Scanned items deduct one package (used up)"},
}

TAPE_GEOMETRY = {
    12: {"printable": 9.878, "top": 0.92},
    24: {"printable": 18.1, "top": 2.95},
}
PX_PER_MM = 12  # label raster density (matches LabelGenerator's cut marks)
PT_PER_MM = 0.352778  # 1 pt = 1/72 inch

# Element fields available in the editor toolbox. "qr"/"ean" are graphics
# (QR of the item's consume link resp. an EAN-13 of the barcode), the rest
# are text fields resolved against the item or control-code data.
LABEL_FIELDS = ("name", "category", "barcode", "text", "qr", "ean")

# Preset layouts in the LabelGenerator style (its Gridfinity preset is
# intentionally not carried over — pantry shelves, not workshop bins).
# Boxes are mm offsets within the tape's printable area.
PRESETS = {
    "mm12": {
        "tape": 12, "widthMm": 50,
        "elements": [
            {"id": "name", "field": "name", "x": 1.1, "y": 0.9, "w": 37.5,
             "h": 8.0, "fontSizePt": 14, "text": ""},
            {"id": "qr", "field": "qr", "x": 39.9, "y": 0.3, "w": 9.3,
             "h": 9.3, "fontSizePt": 0, "text": ""},
        ],
    },
    "mm24": {
        "tape": 24, "widthMm": 50,
        "elements": [
            {"id": "name", "field": "name", "x": 1.5, "y": 2.2, "w": 36.5,
             "h": 13.5, "fontSizePt": 29, "text": ""},
            {"id": "qr", "field": "qr", "x": 39.0, "y": 4.5, "w": 9.5,
             "h": 9.5, "fontSizePt": 0, "text": ""},
        ],
    },
    "storage24": {
        "tape": 24, "widthMm": 50,
        "elements": [
            {"id": "name", "field": "name", "x": 2, "y": 1.5, "w": 20,
             "h": 6.5, "fontSizePt": 18, "text": ""},
            {"id": "category", "field": "category", "x": 2, "y": 9.5, "w": 31,
             "h": 4.5, "fontSizePt": 10, "text": ""},
            {"id": "note", "field": "text", "x": 2, "y": 14.5, "w": 31,
             "h": 3.5, "fontSizePt": 7, "text": ""},
            {"id": "qr", "field": "qr", "x": 23, "y": 2, "w": 10,
             "h": 10, "fontSizePt": 0, "text": ""},
        ],
    },
}

# Fallback for the "which preset fits this tape" save call.
PRESET_FOR_TAPE = {12: "mm12", 24: "mm24"}

# Default design of the bought/trash control stickers before the user
# customizes them: caption + the code graphic.
DEFAULT_CONTROL_LAYOUT = [
    {"id": "caption", "field": "name", "x": 1.5, "y": 1.2, "w": 22,
     "h": 5.5, "fontSizePt": 15, "text": ""},
    {"id": "code", "field": "ean", "x": 1.5, "y": 7.2, "w": 46,
     "h": 10.5, "fontSizePt": 0, "text": ""},
]

FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def _font(px: int):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _new_canvas(height_px: int, width_px: int) -> Image.Image:
    return Image.new("RGB", (max(width_px, 1), max(height_px, 1)), "white")


def _qr_image(content: str, box_px: int) -> Image.Image:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=0)
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PilImage).convert("RGB")
    return img.resize((box_px, box_px), Image.NEAREST)


def _ean_image(code: str, height_px: int) -> tuple[Image.Image, bool]:
    """EAN-13 barcode rendered via python-barcode, white margins cropped.
    Bars only — no human-readable digits underneath (the label/table shows
    them separately; on tape they'd just eat height)."""
    code = re.sub(r"\D", "", code)
    if len(code) != 13:
        return _new_canvas(1, 1), False
    try:
        buffer = io.BytesIO()
        barcode_lib.EAN13(code, writer=ImageWriter()).write(buffer, options={
            "write_text": False,
            "module_height": max(height_px // 10, 8),
            "quiet_zone": 2,
        })
        buffer.seek(0)
        img = Image.open(buffer).convert("RGB")
    except Exception:  # noqa: BLE001 — invalid check digit etc.
        return _new_canvas(1, 1), False
    gray = img.convert("L")
    bbox = gray.point(lambda p: 0 if p > 240 else 255).getbbox()
    if bbox:
        img = img.crop(bbox)
    return img, True


def _text_in_box(text: str, font_pt: float, box_w_px: int,
                 box_h_px: int) -> Image.Image | None:
    """One line of bold black text, left-aligned and vertically centered
    inside its mm box, shrinking until it fits the box width (clips at
    LabelGenerator's minimum of 4 pt)."""
    text = (text or "").strip()
    if not text or box_w_px < 2 or box_h_px < 2:
        return None
    size = max(font_pt, 4)
    while size > 4:
        font_px = max(2, int(round(size * PT_PER_MM * PX_PER_MM)))
        font = _font(font_px)
        _, _, w, _ = font.getbbox(text)
        if w <= box_w_px and font_px <= box_h_px:
            break
        size -= 0.5
    font_px = max(2, int(round(size * PT_PER_MM * PX_PER_MM)))
    font = _font(font_px)
    _, _, w, h = font.getbbox(text)
    img = _new_canvas(max(box_h_px, h + 2), box_w_px)
    ImageDraw.Draw(img).text((0, (box_h_px - h) // 2), text, fill="black", font=font)
    return img


def _resolve_field(field: str, data: dict, element: dict) -> str:
    if field == "text":
        return element.get("text") or ""
    return data.get(field, "") or ""


def item_label_data(item: dict, base_url: str) -> dict:
    """Field values a custom item design resolves against: the QR links to
    the item's consume page (/c/<id>, same URL as the NFC/QR tag), the EAN
    graphic shows the primary product barcode."""
    barcode = item.get("barcode")
    return {
        "name": item.get("name") or "",
        "category": item.get("category") or "",
        "barcode": barcode or "",
        "qr": f"{base_url.rstrip('/')}/c/{item['id']}",
        "ean": barcode or "",
    }


def control_label_data(control: str) -> dict:
    """Field values for a control-code sticker design: the caption is the
    code's name, the barcode/QR/EAN graphics all carry its digits."""
    meta = CONTROL_CODES[control]
    return {
        "name": meta["label"],
        "category": "",
        "barcode": meta["code"],
        "qr": meta["code"],
        "ean": meta["code"],
    }


def render_custom_label(elements: list[dict], data: dict,
                        width_mm: float = 50, tape_mm: int = 24,
                        qr_instead_of_ean: bool = False) -> Image.Image:
    """Render one custom label design: white canvas of (width_mm × tape
    printable height) with each element placed at its mm offset. QR boxes
    stay square inside their box; EAN graphics scale into theirs (the
    print-sticker toggle can swap them for QRs of the same digits)."""
    tape = tape_mm if tape_mm in TAPE_GEOMETRY else 24
    try:
        width = max(10.0, min(300.0, float(width_mm or 50)))
    except (TypeError, ValueError):
        width = 50.0
    height_px = int(TAPE_GEOMETRY[tape]["printable"] * PX_PER_MM)
    canvas = _new_canvas(height_px, int(width * PX_PER_MM))
    for element in elements or []:
        if not isinstance(element, dict):
            continue
        field = str(element.get("field") or "").lower()
        if qr_instead_of_ean and field == "ean":
            field = "qr"
        try:
            x = max(0.0, float(element.get("x") or 0))
            y = max(0.0, float(element.get("y") or 0))
            w = float(element.get("w") or 10)
            h = float(element.get("h") or 5)
        except (TypeError, ValueError):
            continue
        box_x, box_y = int(x * PX_PER_MM), int(y * PX_PER_MM)
        box_w, box_h = max(1, int(w * PX_PER_MM)), max(1, int(h * PX_PER_MM))
        if field == "qr":
            content = data.get("qr") or ""
            if not content:
                continue
            side = min(box_w, box_h)
            img = _qr_image(content, side)
            canvas.paste(img, (box_x + (box_w - side) // 2, box_y + (box_h - side) // 2))
        elif field == "ean":
            code = data.get("ean") or ""
            img, rendered = _ean_image(code, box_h)
            if not rendered:
                continue
            img.thumbnail((box_w, box_h), Image.LANCZOS)
            canvas.paste(img, (box_x + (box_w - img.width) // 2,
                               box_y + (box_h - img.height) // 2))
        elif field in LABEL_FIELDS:
            value = _resolve_field(field, data, element)
            text_img = _text_in_box(value, float(element.get("fontSizePt") or 10),
                                    box_w, box_h)
            if text_img is not None:
                canvas.paste(text_img, (box_x, box_y))
    return canvas


def default_elements(tape_mm: int = 24) -> list[dict]:
    """Starting layout when a design is created without elements (the
    'Create custom label' checkbox): the tape's preset design."""
    preset = PRESETS[PRESET_FOR_TAPE.get(tape_mm, 24)]
    return [dict(el) for el in preset["elements"]]


def _dashed_cut_line(height_mm: float) -> Image.Image:
    """Vertical dashed line between labels; coarse dashes survive Epson's
    threshold dithering (LabelGenerator finding)."""
    height_px = int(height_mm * PX_PER_MM)
    img = _new_canvas(height_px, 32)
    draw = ImageDraw.Draw(img)
    for y in range(0, height_px, 25):
        draw.rectangle([13, y, 19, min(y + 15, height_px)], fill="black")
    return img


def _jpeg_b64(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=100)
    return base64.b64encode(buffer.getvalue()).decode()


def generate_lemd(images: list[Image.Image], tape_mm: int = 24) -> str:
    """Stitch label images into one Epson Label Editor mobile (.lemd) strip,
    dash-separated for cutting."""
    tape = tape_mm if tape_mm in TAPE_GEOMETRY else 24
    geo = TAPE_GEOMETRY[tape]
    top_y, bottom_y = geo["top"], geo["top"] + geo["printable"]

    cut_margin_mm = 4.0
    current_x = 1.0
    cut_line = _dashed_cut_line(geo["printable"])

    def at_y(y: float) -> float:
        return round(y, 2)

    def image_object(source_b64: str, x: float, width_mm: float) -> dict:
        return {
            "object_type": "image",
            "block_info": {
                "points": [
                    {"x": at_y(x), "y": at_y(top_y)},
                    {"x": round(x + width_mm, 2), "y": at_y(bottom_y)},
                ],
                "flopped": False, "locked": False, "flipped": False, "rotation": 0,
            },
            "image": {"dither": "threshold", "is_symbol": False,
                      "threshold": 128, "source": source_b64},
        }

    objects = []
    for index, img in enumerate(images):
        image_width_mm = tape * (img.width / img.height)
        objects.append(image_object(_jpeg_b64(img), current_x, image_width_mm))
        current_x += image_width_mm
        if index < len(images) - 1:
            line_x = current_x + cut_margin_mm / 2 - 1.0
            objects.append(image_object(_jpeg_b64(cut_line), line_x, 2.0))
            current_x += cut_margin_mm
        else:
            current_x += 1.0  # end margin

    payload = {
        "version": "1.2.0",
        "signature": "Epson Label Editor mobile layout data",
        "tape_config": {
            "width": tape,
            "auto_length": True,
            "margin": 1,
            "length": round(current_x),
            "kind": "tape",
        },
        "object_list": objects,
    }
    return json.dumps(payload)
