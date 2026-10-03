"""Make a fake 'completed and phone-scanned' packet from a real rendered packet."""

import io
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

from hs import layout as L

FONT_PATHS = ["/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"]


def font(size):
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def fill_in(packet: Path, answers: dict, marks: dict, dpi=150) -> list[Image.Image]:
    """answers: {(page, slot): text}; marks: {(page, slot, 'stuck'|'easy'): fill 0..1}."""
    s = dpi / 72
    pages = []
    for n, page in enumerate(pdfium.PdfDocument(str(packet)), 1):
        img = page.render(scale=s).to_pil().convert("L")
        d = ImageDraw.Draw(img)
        for (pg, slot), text in answers.items():
            if pg == n:
                x, y, w, h = L.answer_box(slot)
                d.text(((x + 10) * s, (y + 14) * s), text, fill=70, font=font(int(26 * s)))
                d.text(((64) * s, (L.slot_top(slot) + 50) * s), "work...", fill=110, font=font(int(14 * s)))
        for (pg, slot, which), amount in marks.items():
            if pg == n:
                cx, cy, r = L.bubble(slot, which)
                if amount >= 1:
                    rr = r * 0.85
                    d.ellipse([(cx - rr) * s, (cy - rr) * s, (cx + rr) * s, (cy + rr) * s], fill=80)
                else:  # a small tick: an ambiguous mark
                    d.line([((cx - 4) * s, cy * s), (cx * s, (cy + 4) * s), ((cx + 6) * s, (cy - 6) * s)], fill=60, width=int(2 * s))
        pages.append(img)
    return pages


def phone_scan(img: Image.Image, seed: int) -> Image.Image:
    """Rotate, perspective-warp onto a table, uneven light, blur, noise, JPEG."""
    rng = np.random.default_rng(seed)
    a = np.array(img)
    h, w = a.shape
    canvas = np.full((int(h * 1.15), int(w * 1.15)), 95, np.uint8)  # dark table around the paper
    oy, ox = (canvas.shape[0] - h) // 2, (canvas.shape[1] - w) // 2
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jitter = rng.uniform(-0.03, 0.03, (4, 2)) * [w, h]
    dst = np.float32(src + [ox, oy] + jitter)
    M = cv2.getPerspectiveTransform(src, dst)
    canvas = cv2.warpPerspective(a, M, canvas.shape[::-1], dst=canvas, borderMode=cv2.BORDER_TRANSPARENT)
    rot = cv2.getRotationMatrix2D((canvas.shape[1] / 2, canvas.shape[0] / 2), rng.uniform(-4, 4), 1.0)
    canvas = cv2.warpAffine(canvas, rot, canvas.shape[::-1], borderValue=95)
    light = np.linspace(0.82, 1.0, canvas.shape[1])[None, :]  # shadow across the page
    canvas = canvas * light + rng.normal(0, 6, canvas.shape)
    canvas = cv2.GaussianBlur(np.clip(canvas, 0, 255).astype(np.uint8), (3, 3), 0)
    buf = io.BytesIO()
    Image.fromarray(canvas).save(buf, "JPEG", quality=70)
    return Image.open(io.BytesIO(buf.getvalue()))


def to_pdf(images: list[Image.Image], path: Path):
    images[0].convert("RGB").save(path, save_all=True, append_images=[i.convert("RGB") for i in images[1:]])
