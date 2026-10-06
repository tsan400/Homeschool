"""Scan input: PDF/image pages -> straightened page images, QR payloads, crops, marks."""

from dataclasses import dataclass

import cv2
import numpy as np
import pypdfium2 as pdfium
import zxingcpp

from hs import layout as L

DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
INK = 0.85             # a pixel is ink if darker than this fraction of the paper around it
SEARCH = 10            # pixels: how far a patch may be off after straightening (paper curl)
# Marks are measured as ink that isn't on the blank printed page, so a tick, a cross and a
# filled circle all count. Tuned on real phone photos of light pencil: empty circles read
# up to 0.007, ticks 0.029 and up; empty boxes 0.000, a single faint "1" 0.0035.
BUBBLE_MARKED = 0.02   # share of the area around a circle that is the child's ink
BUBBLE_EMPTY = 0.012   # between the two -> "unclear", sent to review
BLANK_INK = 0.001      # answer box with less of the child's ink than this is blank
WRITTEN = 0.003        # narration page with more of the child's ink than this was written on


class ScanError(Exception):
    pass


@dataclass
class Page:
    image: np.ndarray   # straightened grayscale page, PAGE_W*scale x PAGE_H*scale
    scale: float        # pixels per point
    qr: dict            # parsed payload: worksheet, page
    paper: float        # brightness of blank paper
    blank: np.ndarray | None = None  # the same page as printed, rendered at the same scale
    slots: int = L.LEGACY_SLOTS      # problems on this page, from the packet's layout
    top: float = L.BODY_TOP          # where they start (lower on page 1, under the word and weather)
    _paper_map: np.ndarray | None = None

    def paper_map(self) -> np.ndarray:
        """Brightness of the paper around each pixel (strokes removed), so shadows and uneven
        light don't hide faint pencil or turn into fake marks."""
        if self._paper_map is None:
            self._paper_map = cv2.GaussianBlur(cv2.dilate(self.image, np.ones((15, 15), np.uint8)), (0, 0), 15)
        return self._paper_map

    def px(self, v: float) -> int:
        return int(round(v * self.scale))

    def crop(self, x, y, w, h, pad=0.0) -> np.ndarray:
        return self.image[self.px(y - pad):self.px(y + h + pad), self.px(x - pad):self.px(x + w + pad)]

    def added_ink(self, x, y, w, h) -> np.ndarray:
        """Boolean mask of ink in this area that isn't printed on the blank page.
        The area is first aligned locally against the blank page, because a curled page in a
        phone photo can still be a few pixels off after straightening."""
        x0, y0, x1, y1 = self.px(x), self.px(y), self.px(x + w), self.px(y + h)
        printed = self.blank[y0:y1, x0:x1]
        window = (slice(max(0, y0 - SEARCH), y1 + SEARCH), slice(max(0, x0 - SEARCH), x1 + SEARCH))
        around, paper = self.image[window], self.paper_map()[window]
        match = cv2.matchTemplate(around.astype(np.float32), printed.astype(np.float32), cv2.TM_CCOEFF_NORMED)
        dx, dy = cv2.minMaxLoc(match)[3]
        at = (slice(dy, dy + printed.shape[0]), slice(dx, dx + printed.shape[1]))
        mask = cv2.dilate((printed < 200).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        return (around[at] < paper[at] * INK) & ~mask

    def bubble_fill(self, slot: int, which: str) -> float:
        return self.mark_fill(*L.bubble(slot, which, self.slots, self.top))

    def mark_fill(self, cx: float, cy: float, r: float) -> float:
        """Share of the area around a printed circle covered by the child's ink."""
        R = r * 1.4  # ticks often stray past the outline
        added = self.added_ink(cx - R, cy - R, 2 * R, 2 * R)
        h, w = added.shape
        yy, xx = np.mgrid[:h, :w]
        disc = (xx - w / 2 + 0.5) ** 2 + (yy - h / 2 + 0.5) ** 2 <= (min(h, w) / 2) ** 2
        return float(added[disc].mean())

    def answer_ink(self, slot: int) -> float:
        """Share of the box's inside covered by the child's ink. The border itself is left out:
        on a curled page it never lines up exactly and would look like writing."""
        x, y, w, h = L.answer_box(slot, self.slots, self.top)
        added = self.added_ink(x - 4, y - 4, w + 8, h + 8)
        k = self.px(8)
        return float(added[k:-k, k:-k].mean())

    def writing(self) -> float:
        """Share of a narration page's lined area covered by the child's ink."""
        top = L.NARRATION_TOP - L.LINE_GAP
        return float(self.added_ink(56, top, L.PAGE_W - 112, L.BODY_BOTTOM - top).mean())

    def answer_png(self, slot: int) -> bytes:
        """The answer box plus a small margin, for the handwriting reader and the review queue."""
        ok, buf = cv2.imencode(".png", self.crop(*L.answer_box(slot, self.slots, self.top), pad=6))
        return buf.tobytes()


    def jpeg(self, quality=80) -> bytes:
        """The whole straightened page, for viewing in the portal."""
        ok, buf = cv2.imencode(".jpg", self.image, [cv2.IMWRITE_JPEG_QUALITY, quality])
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
    """Decode the page's QR code. Phone photos can be soft, shadowed or noisy, so try ZXing, then
    two OpenCV detectors on progressively cleaned-up versions of the QR corner, then the whole page."""
    x, y, s = L.QR
    m = 20
    region = page[int((y - m) * scale):int((y + s + m) * scale), int((x - m) * scale):int((x + s + m) * scale)]
    for candidate in (region, page):
        for found in zxingcpp.read_barcodes(candidate, formats=zxingcpp.BarcodeFormat.QRCode):
            if payload := L.parse_qr(found.text):
                return payload
    big = cv2.resize(region, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    sharp = cv2.addWeighted(big, 2.0, cv2.GaussianBlur(big, (0, 0), 4), -1.0, 0)
    otsu = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    for det in (cv2.QRCodeDetectorAruco(), cv2.QRCodeDetector()):
        for candidate in (region, big, otsu, page):
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
