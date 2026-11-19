"""Item-label rendering and Epson Label Editor mobile (.lemd) export.

Mirrors the pipeline of LabelGenerator (github.com/NooFlo/LabelGenerator):
QR codes and EAN-13 barcodes composed into PNG labels sized for 12/24 mm
thermal tape, then batches stitched into a continuous .lemd strip with
dashed cut marks. The .lemd file is imported into the Epson Label Editor
mobile app, which prints it over Bluetooth.

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

# Scanner control codes: sticky modes switched by scanning one of these EAN-13
# stickers. GS1 in-store reserved range (20xxxxxxxxxx — no product collides).
CONTROL_CODES = {
    "bought": {"code": "2000000000008", "label": "BOUGHT",
                "hint": "Scanned items are restocked (+1 package)"},
    "empty": {"code": "2000000000015", "label": "EMPTY / TRASH",
              "hint": "Scanned items go to zero and land on the shopping list"},
    "consume": {"code": "2000000000022", "label": "CONSUME",
                "hint": "Back to the default: one package used up"},
}

TAPE_GEOMETRY = {
    12: {"printable": 9.878, "top": 0.92},
    24: {"printable": 18.1, "top": 2.95},
}
PX_PER_MM = 12  # label raster density (matches LabelGenerator's cut marks)

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


def _text_image(text: str, font_px: int, max_width_px: int | None = None) -> Image.Image:
    """One line of bold black text, shrinking to fit max_width_px."""
    text = text.strip() or "-"
    size = font_px
    while size > 8:
        font = _font(size)
        _, _, w, _ = font.getbbox(text)
        if max_width_px is None or w <= max_width_px:
            break
        size -= 2
    font = _font(size)
    _, _, w, h = font.getbbox(text)
    img = _new_canvas(h + 4, w + 4)
    ImageDraw.Draw(img).text((2, 2), text, fill="black", font=font)
    return img


def _qr_image(content: str, box_px: int) -> Image.Image:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=0)
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PilImage).convert("RGB")
    return img.resize((box_px, box_px), Image.NEAREST)


def _ean_image(code: str, height_px: int) -> tuple[Image.Image, bool]:
    """EAN-13 barcode rendered via python-barcode, white margins cropped."""
    code = re.sub(r"\D", "", code)
    if len(code) != 13:
        return _new_canvas(1, 1), False
    try:
        buffer = io.BytesIO()
        barcode_lib.EAN13(code, writer=ImageWriter()).write(buffer, options={
            "module_height": max(height_px // 10, 8),
            "font_size": max(height_px // 6, 10),
            "text_distance": 3,
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


def _paste_row(canvas: Image.Image, images: list[Image.Image], gap_px: int) -> Image.Image:
    x = gap_px
    for img in images:
        canvas.paste(img, (x, max(0, (canvas.height - img.height) // 2)))
        x += img.width + gap_px
    return canvas


def item_label(item: dict, base_url: str, tape_mm: int = 24) -> Image.Image:
    """Shelf label for an inventory item: QR linking to the consume landing
    page (/c/<id>, the same URL as the NFC/QR tag) plus the item name; on
    24 mm tape the product barcode joins to the right."""
    tape = tape_mm if tape_mm in TAPE_GEOMETRY else 24
    height = int(TAPE_GEOMETRY[tape]["printable"] * PX_PER_MM)
    gap = PX_PER_MM
    qr = _qr_image(f"{base_url.rstrip('/')}/c/{item['id']}",
                   height if tape == 12 else height - 4)
    blocks = [qr, _text_image(item["name"], height // 2)]
    if tape == 24 and item.get("barcode"):
        code_img, rendered = _ean_image(item["barcode"], height)
        if rendered:
            code_img.thumbnail((height * 20, height), Image.LANCZOS)
            blocks.append(code_img)
    width = gap + sum(img.width + gap for img in blocks)
    return _paste_row(_new_canvas(height, width), blocks, gap)


def control_code_labels(tape_mm: int = 24) -> list[tuple[Image.Image, str, str]]:
    """One label per scanner control code: caption + EAN-13 graphic."""
    tape = tape_mm if tape_mm in TAPE_GEOMETRY else 24
    height = int(TAPE_GEOMETRY[tape]["printable"] * PX_PER_MM)
    labels = []
    for meta in CONTROL_CODES.values():
        caption = _text_image(meta["label"], int(height * 0.42))
        code_img, rendered = _ean_image(meta["code"], height)
        if not rendered:
            continue
        code_img.thumbnail((height * 20, int(height * 0.95)), Image.LANCZOS)
        canvas = _new_canvas(height, caption.width + code_img.width + 3 * PX_PER_MM)
        _paste_row(canvas, [caption, code_img], PX_PER_MM)
        labels.append((canvas, meta["label"], meta["code"]))
    return labels


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
