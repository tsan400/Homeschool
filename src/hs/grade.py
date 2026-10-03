"""Grading: compare transcribed answers to computed keys, and the `hs grade` pipeline."""

import json
import re
import shutil
from fractions import Fraction
from math import gcd
from pathlib import Path

from hs import config, db, read, scan

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

def write_grades(con, ws_id: str):
    ws = db.worksheet(con, ws_id)
    rows = [{k: r[k] for k in ("number", "page", "skill", "level", "kind", "prompt", "answer", "transcription",
                               "confidence", "correct", "stuck", "too_easy", "reason", "reviewed", "excluded")}
            for r in db.results(con, ws_id)]
    path = config.day_dir(ws["date"], ws["student"]) / "grades.json"
    path.write_text(json.dumps({"worksheet": ws_id, "status": ws["status"], "problems": rows}, indent=1))


def grade_file(path: Path, transcribe=read.transcribe) -> list[str]:
    """Grade one scan file. Returns report lines."""
    st = config.settings()
    con = db.connect()
    report, by_ws = [], {}
    for page in scan.pages(path, st["scan_dpi"]):
        if isinstance(page, scan.ScanError):
            report.append(f"  ! {page}")
        else:
            by_ws.setdefault(page.qr["worksheet"], []).append(page)

    for ws_id, pages in by_ws.items():
        ws = db.worksheet(con, ws_id)
        if ws is None:
            report.append(f"  ! unknown worksheet {ws_id}")
            continue
        if ws["status"] == "approved":
            report.append(f"  ! {ws_id} is already approved; ignoring these pages")
            continue
        folder = config.day_dir(ws["date"], ws["student"])
        (folder / "crops").mkdir(exist_ok=True)
        meta, items = {}, []
        for page in pages:
            for p in db.problems(con, ws_id, page.qr["page"]):
                crop = folder / "crops" / f"{p['number']:02d}.png"
                crop.write_bytes(page.answer_png(p["slot"]))
                blank = page.answer_ink(p["slot"]) < scan.BLANK_INK
                meta[p["id"]] = dict(p=p, blank=blank, crop=str(crop),
                                     stuck=page.bubble_fill(p["slot"], "stuck"), easy=page.bubble_fill(p["slot"], "easy"))
                if not blank:
                    items.append({"id": str(p["id"]), "png": crop.read_bytes(), "hint": p["hint"]})
        reads = transcribe(items)

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
                marks[which] = fill >= scan.BUBBLE_FILLED
                if scan.BUBBLE_EMPTY < fill < scan.BUBBLE_FILLED:
                    reasons.append(f"unclear '{which}' mark")
            con.execute("""INSERT OR REPLACE INTO response (problem_id, transcription, confidence, blank, stuck, too_easy,
                           stuck_fill, easy_fill, correct, reason, crop) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (pid, text, conf, int(m["blank"]), int(marks["stuck"]), int(marks["too easy"]),
                         m["stuck"], m["easy"], int(bool(correct)), "; ".join(reasons), m["crop"]))

        rows = db.results(con, ws_id)
        status = "graded" if all(r["scanned"] for r in rows) else "partial"
        con.execute("UPDATE worksheet SET status=? WHERE id=?", (status, ws_id))
        con.commit()
        n = 1
        while (dest := folder / f"scan{'' if n == 1 else f'-{n}'}{path.suffix.lower()}").exists():
            n += 1
        shutil.copy(path, dest)
        write_grades(con, ws_id)

        scanned = [r for r in rows if r["scanned"]]
        flagged = sum(bool(r["reason"]) for r in scanned)
        report.append(f"  {ws_id}: {sum(r['correct'] for r in scanned)}/{len(scanned)} correct, "
                      f"{sum(r['stuck'] for r in scanned)} stuck, {flagged} to review"
                      + ("" if status == "graded" else f", {len(rows) - len(scanned)} problems not scanned yet"))
    return report
