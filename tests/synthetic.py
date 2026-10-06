"""Make a fake 'completed and phone-scanned' packet from a real rendered packet."""

import io
import json
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


def layout_of(con, ws_id) -> dict:
    """{page: (slots, top)}, the way the packet was printed."""
    from hs import db
    return {p["page"]: (p.get("slots", L.LEGACY_SLOTS), p.get("top", L.BODY_TOP))
            for p in json.loads(db.worksheet(con, ws_id)["pages"])}


def fill_in(packet: bytes, answers: dict, marks: dict, dpi=150, slots=6, ticks=(), writing=None,
            layout=None) -> list[Image.Image]:
    """packet: PDF bytes. answers: {(page, slot): text}; marks: {(page, slot, 'stuck'|'easy'): fill 0..1};
    ticks: [(page, cx, cy)] checkmarks anywhere (the French circle); writing: {page: [lines]} on a narration page.
    layout: {page: (slots, top)} from layout_of(); pages not in it have `slots` problems from the usual top."""
    where = lambda pg: (layout or {}).get(pg, (slots, L.BODY_TOP))
    s = dpi / 72
    pages = []
    for n, page in enumerate(pdfium.PdfDocument(packet), 1):
        img = page.render(scale=s).to_pil().convert("L")
        d = ImageDraw.Draw(img)
        for (pg, slot), text in answers.items():
            if pg == n:
                text, shade = text if isinstance(text, tuple) else (text, 70)  # (text, 200) = faint pencil
                x, y, w, h = L.answer_box(slot, *where(pg))
                d.text(((x + 10) * s, (y + 14) * s), text, fill=shade, font=font(int(18 * s)) if shade > 100 else font(int(26 * s)))
                d.text(((64) * s, (L.slot_top(slot, *where(pg)) + 50) * s), "work...", fill=110, font=font(int(14 * s)))
        for (pg, slot, which), amount in marks.items():
            if pg == n:
                cx, cy, r = L.bubble(slot, which, *where(pg))
                if amount >= 1:
                    rr = r * 0.85
                    d.ellipse([(cx - rr) * s, (cy - rr) * s, (cx + rr) * s, (cy + rr) * s], fill=80)
                elif amount >= 0.5:  # a tick, the way children actually mark it: counts as marked
                    d.line([((cx - 6) * s, cy * s), ((cx - 1) * s, (cy + 6) * s), ((cx + 10) * s, (cy - 12) * s)], fill=90, width=int(1.5 * s))
                else:  # a stray dot: too little to call, goes to review
                    rr = 0.9
                    d.ellipse([(cx - rr) * s, (cy - rr) * s, (cx + rr) * s, (cy + rr) * s], fill=80)
        for pg, cx, cy in ticks:
            if pg == n:
                d.line([((cx - 6) * s, cy * s), ((cx - 1) * s, (cy + 6) * s), ((cx + 10) * s, (cy - 12) * s)], fill=90, width=int(1.5 * s))
        for i, line in enumerate((writing or {}).get(n, [])):
            d.text((62 * s, (L.NARRATION_TOP - 22 + i * L.LINE_GAP) * s), line, fill=70, font=font(int(20 * s)))
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


def to_pdf(images: list[Image.Image]) -> bytes:
    buf = io.BytesIO()
    images[0].convert("RGB").save(buf, "PDF", save_all=True, append_images=[i.convert("RGB") for i in images[1:]])
    return buf.getvalue()
