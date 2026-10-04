"""Grading: compare transcribed answers to computed keys, and grade uploaded scans."""

import json
import re
from fractions import Fraction
from math import gcd

import numpy as np
import pypdfium2 as pdfium

from hs import config, db, packets, read, scan, vault

# ---------- answer comparison (pure) ----------

NUMBER = re.compile(r"(-?)(?:(\d+)\s+(\d+)/(\d+)|(\d+)/(\d+)|(\d*\.?\d+))")


def clean(text: str) -> str:
    t = (text or "").strip().replace("−", "-").replace("–", "-").replace(",", "").replace("$", "")
    t = re.sub(r"^[a-z]\s*=\s*", "", t, flags=re.I)  # "x = 5" -> "5"
    return t.rstrip("%").strip()


def parse_number(text: str) -> tuple[Fraction, bool] | None:
    """-> (value, written_in_lowest_terms) or None if it isn't a single number."""
    m = NUMBER.fullmatch(clean(text))
    if not m:
        return None
    sign = -1 if m[1] else 1
    if m[2]:  # mixed number
        whole, n, d = int(m[2]), int(m[3]), int(m[4])
        if d == 0:
            return None
        return sign * (whole + Fraction(n, d)), gcd(n, d) == 1 and n < d
    if m[5]:
        n, d = int(m[5]), int(m[6])
        if d == 0:
            return None
        return sign * Fraction(n, d), gcd(n, d) == 1
    return sign * Fraction(m[7]), True


def parse_remainder(text: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"(\d+)\s*(?:r\s*(\d+))?", clean(text), flags=re.I)
    return (int(m[1]), int(m[2] or 0)) if m else None


def check(text: str, key: str, form: str) -> bool | None:
    """True/False, or None when the child's answer can't be parsed (sent to review)."""
    if form == "remainder":
        got, want = parse_remainder(text), parse_remainder(key)
        return None if got is None else got == want
    got, want = parse_number(text), parse_number(key)
    if got is None:
        return None
    return got[0] == want[0] and (form != "lowest" or got[1])


# ---------- pipeline ----------

def crop_name(ws_id: str, number: int) -> str:
    return f"ws/{ws_id}/crop-{number:02d}.png"


def page_name(ws_id: str, page: int) -> str:
    return f"ws/{ws_id}/page-{page}.jpg"


def grade_scan(con, family_id: int, data: bytes, transcribe=read.transcribe) -> tuple[list[str], bool]:
    """Grade one uploaded scan (PDF or photo, in memory) for a family. Page images and answer
    crops are saved encrypted to the family's files. Returns (report lines, every page used)."""
    st = config.settings()
    report, by_ws, complete = [], {}, True
    try:
        pages = scan.pages(data, st["scan_dpi"])
    except scan.ScanError as e:
        return [f"! {e}"], False
    for page in pages:
        if isinstance(page, scan.ScanError):
            report.append(f"! {page}")
            complete = False
        else:
            by_ws.setdefault(page.qr["worksheet"], []).append(page)

    for ws_id, pages in by_ws.items():
        ws = db.worksheet(con, ws_id)
        if ws is None or db.family_of_worksheet(con, ws_id) != family_id:
            report.append(f"! a page belongs to a packet this account didn't print ({ws_id})")
            complete = False
            continue
        if ws["status"] == "approved":
            report.append(f"! {ws_id} is already approved; ignoring these pages")
            continue
        meta, items = {}, []
        scanned_pages = set(json.loads(ws["scanned_pages"]))
        printed = pdfium.PdfDocument(vault.get(con, family_id, packets.packet_name(ws_id)))
        for page in pages:
            n = page.qr["page"]
            page.blank = np.array(printed[n - 1].render(scale=page.scale, grayscale=True).to_pil().convert("L"))
            vault.put(con, family_id, page_name(ws_id, n), page.jpeg())
            scanned_pages.add(n)
            for p in db.problems(con, ws_id, n):
                png = page.answer_png(p["slot"])
                crop = crop_name(ws_id, p["number"])
                vault.put(con, family_id, crop, png)
                blank = page.answer_ink(p["slot"]) < scan.BLANK_INK
                meta[p["id"]] = dict(p=p, blank=blank, crop=crop,
                                     stuck=page.bubble_fill(p["slot"], "stuck"), easy=page.bubble_fill(p["slot"], "easy"))
                if not blank:
                    items.append({"id": str(p["id"]), "png": png, "hint": p["hint"]})
        reads = transcribe(items) if items else {}

        for pid, m in meta.items():
            p, reasons = m["p"], []
            if m["blank"]:
                text, conf, correct = "", 1.0, False
            else:
                r = reads[str(pid)]
                text, conf = r["text"], float(r["confidence"])
                correct = check(text, p["answer"], p["form"])
                if correct is None:
                    reasons.append("answer not understood")
                if conf < st["confidence_threshold"]:
                    reasons.append(f"low confidence ({conf:.2f})" + (f": {r['note']}" if r.get("note") else ""))
            marks = {}
            for which, fill in (("stuck", m["stuck"]), ("too easy", m["easy"])):
                marks[which] = fill >= scan.BUBBLE_MARKED
                if scan.BUBBLE_EMPTY < fill < scan.BUBBLE_MARKED:
                    reasons.append(f"unclear '{which}' mark")
            con.execute("""INSERT OR REPLACE INTO response (problem_id, transcription, confidence, blank, stuck, too_easy,
                           stuck_fill, easy_fill, correct, reason, crop) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (pid, text, conf, int(m["blank"]), int(marks["stuck"]), int(marks["too easy"]),
                         m["stuck"], m["easy"], int(bool(correct)), "; ".join(reasons), m["crop"]))

        rows = db.results(con, ws_id)
        status = "graded" if all(r["scanned"] for r in rows) else "partial"
        con.execute("UPDATE worksheet SET status=?, scanned_pages=? WHERE id=?",
                    (status, json.dumps(sorted(scanned_pages)), ws_id))
        con.commit()

        scanned = [r for r in rows if r["scanned"]]
        flagged = sum(bool(r["reason"]) for r in scanned)
        name = db.student(con, ws["student"])["name"]
        report.append(f"{name}, {ws['date']}: {sum(r['correct'] for r in scanned)}/{len(scanned)} correct, "
                      f"{sum(r['stuck'] for r in scanned)} stuck, {flagged} to review"
                      + ("" if status == "graded" else f", {len(rows) - len(scanned)} problems not scanned yet"))
    return report, complete
