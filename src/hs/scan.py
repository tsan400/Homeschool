"""Scan input: PDF/image pages -> straightened page images, QR payloads, crops, bubble fill."""

from dataclasses import dataclass

import cv2
import numpy as np
import pypdfium2 as pdfium

from hs import layout as L

DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
INK = 0.70             # a pixel is ink if darker than this fraction of the paper's brightness
BUBBLE_FILLED = 0.45   # share of a bubble's interior that is ink
BUBBLE_EMPTY = 0.12
BLANK_INK = 0.004      # answer box with less ink than this is blank


class ScanError(Exception):
    pass


@dataclass
class Page:
    image: np.ndarray   # straightened grayscale page, PAGE_W*scale x PAGE_H*scale
    scale: float        # pixels per point
    qr: dict            # parsed payload: student, date, worksheet, page
    paper: float        # brightness of blank paper

    def px(self, v: float) -> int:
        return int(round(v * self.scale))

    def crop(self, x, y, w, h, pad=0.0) -> np.ndarray:
        return self.image[self.px(y - pad):self.px(y + h + pad), self.px(x - pad):self.px(x + w + pad)]

    def ink(self, region: np.ndarray) -> np.ndarray:
        return region < self.paper * INK

    def bubble_fill(self, slot: int, which: str) -> float:
        cx, cy, r = L.bubble(slot, which)
        inner = r * 0.6  # stay inside the printed outline
        region = self.crop(cx - inner, cy - inner, 2 * inner, 2 * inner)
        h, w = region.shape
        yy, xx = np.mgrid[:h, :w]
        disc = (xx - w / 2 + 0.5) ** 2 + (yy - h / 2 + 0.5) ** 2 <= (min(h, w) / 2) ** 2
        return float(self.ink(region)[disc].mean())

    def answer_ink(self, slot: int) -> float:
        x, y, w, h = L.answer_box(slot)
        return float(self.ink(self.crop(x + 6, y + 6, w - 12, h - 12)).mean())

    def answer_png(self, slot: int) -> bytes:
        """The answer box plus a small margin, for the handwriting reader and the review queue."""
        ok, buf = cv2.imencode(".png", self.crop(*L.answer_box(slot), pad=6))
        return buf.tobytes()


def load_images(data: bytes, dpi: int) -> list[np.ndarray]:
    """Decode a PDF or image held in memory. Nothing is written to disk."""
    if data.startswith(b"%PDF"):
        pdf = pdfium.PdfDocument(data)
        return [np.array(page.render(scale=dpi / 72, grayscale=True).to_pil().convert("L")) for page in pdf]
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ScanError("not a PDF or an image this program can read")
    return [img]


def straighten(img: np.ndarray, scale: float) -> np.ndarray:
    """Find the corner markers and warp the photo/scan onto the canonical page."""
    detector = cv2.aruco.ArucoDetector(DICT, cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(img)
    if ids is None:
        raise ScanError("no corner markers found")
    src, dst = [], []
    for c, i in zip(corners, ids.flatten()):
        if int(i) in L.MARKERS:
            src += c.reshape(4, 2).tolist()
            dst += [(x * scale, y * scale) for x, y in L.marker_corners(int(i))]
    if len(src) < 12:
        raise ScanError(f"only {len(src) // 4} of 4 corner markers found")
    H, _ = cv2.findHomography(np.float32(src), np.float32(dst), cv2.RANSAC, 5.0)
    return cv2.warpPerspective(img, H, (round(L.PAGE_W * scale), round(L.PAGE_H * scale)),
                               borderValue=255, flags=cv2.INTER_AREA)


def read_qr(page: np.ndarray, scale: float) -> dict | None:
    x, y, s = L.QR
    m = 20
    region = page[int((y - m) * scale):int((y + s + m) * scale), int((x - m) * scale):int((x + s + m) * scale)]
    det = cv2.QRCodeDetector()
    for candidate in (region, page):
        text, *_ = det.detectAndDecode(candidate)
        if text and (payload := L.parse_qr(text)):
            return payload
    return None


def pages(data: bytes, dpi: int = 200) -> list[Page | ScanError]:
    """Every page of a scan (bytes in memory), straightened and identified, or the error that stopped it."""
    scale = dpi / 72
    out = []
    for n, img in enumerate(load_images(data, dpi), 1):
        try:
            flat = straighten(img, scale)
            qr = read_qr(flat, scale)
            if not qr:
                raise ScanError("QR code unreadable")
            out.append(Page(flat, scale, qr, float(np.percentile(flat, 90))))
        except ScanError as e:
            out.append(ScanError(f"scan page {n}: {e}"))
    return out
