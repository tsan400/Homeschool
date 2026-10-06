"""QR codes must read from soft, noisy phone photos whatever the worksheet id looks like."""

import io
import secrets
import tempfile
from pathlib import Path

import cv2
import numpy as np
import typst
from PIL import Image

from hs import layout as L
from hs.render import qr_svg
from hs.scan import read_qr

DPI = 200


def printed_qr(payload: str) -> bytes:
    """The QR exactly as the packet prints it, rasterised at a high resolution."""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "qr.svg").write_text(qr_svg(payload))
        Path(d, "main.typ").write_text(f'#set page(width: {L.QR[2]}pt, height: {L.QR[2]}pt, margin: 0pt)\n'
                                       f'#image("qr.svg", width: {L.QR[2]}pt)')
        return typst.compile(str(Path(d, "main.typ")), format="png", ppi=600)


def photographed_qr(payload: str, seed: int) -> np.ndarray:
    """A straightened page with just the QR printed, after blur, noise, shadow and JPEG."""
    s = DPI / 72
    page = np.full((round(L.PAGE_H * s), round(L.PAGE_W * s)), 255, np.uint8)
    qr = np.array(Image.open(io.BytesIO(printed_qr(payload))).convert("L"))
    x, y, size = (round(v * s) for v in L.QR)
    page[y:y + size, x:x + size] = cv2.resize(qr, (size, size), interpolation=cv2.INTER_AREA)
    rng = np.random.default_rng(seed)
    page = cv2.GaussianBlur(page, (5, 5), 1.2) * np.linspace(0.8, 1.0, page.shape[1])[None, :]
    page = np.clip(page + rng.normal(0, 8, page.shape), 0, 255).astype(np.uint8)
    ok, jpg = cv2.imencode(".jpg", page, [cv2.IMWRITE_JPEG_QUALITY, 60])
    return cv2.imdecode(jpg, cv2.IMREAD_GRAYSCALE)


def test_qr_reads_for_many_worksheet_ids():
    for seed in range(40):
        name = secrets.choice(["timothy", "hannah", "maryelizabeth", "jo"])
        ws_id = f"2026-10-{seed % 28 + 1:02d}-{name}-{secrets.token_hex(2)}-math" + secrets.choice(["", "-placement"])
        page = 1 + seed % 6
        assert read_qr(photographed_qr(L.qr_payload(ws_id, page), seed), DPI / 72) == {"worksheet": ws_id, "page": page}


def test_old_or_foreign_codes_are_ignored():
    assert L.parse_qr("HS1|timothy|2026-10-05|2026-10-05-timothy-math|1") is None
    assert L.parse_qr("https://example.com") is None


def test_rounded_codes_still_read_without_zxing(monkeypatch):
    """OpenCV is the fallback, so the rounded style must stay within what it can read too."""
    monkeypatch.setattr("hs.scan.zxingcpp.read_barcodes", lambda *a, **k: [])
    for seed in range(15):
        ws_id = f"2026-11-{seed + 1:02d}-hannah-{secrets.token_hex(2)}-math"
        assert read_qr(photographed_qr(L.qr_payload(ws_id, 2), seed), DPI / 72) == {"worksheet": ws_id, "page": 2}
