"""End to end: print a real packet, fill it in, 'phone scan' it, grade, approve, plan the next day.

The offline test swaps the Claude reader for a stub that returns what we wrote, so it checks
everything except handwriting recognition: markers, QR, alignment, crops, blank detection,
bubbles, grading, review flags, levels, and stuck-problem scaffolding.
Set ANTHROPIC_API_KEY to also run test_live_transcription against the real API.
"""

import json
import os

import pytest
from PIL import Image

from hs import config, db, grade, levels, planner, read, render
from synthetic import fill_in, phone_scan, to_pdf

DATE, NEXT = "2026-10-05", "2026-10-06"


def wrong(answer):
    return "999" if answer != "999" else "998"


@pytest.fixture
def scanned(con, tmp_path):
    ws_id = planner.create(con, "timothy", DATE)
    render.render(con, ws_id, config.day_dir(DATE, "timothy"))
    probs = {p["number"]: p for p in db.problems(con, ws_id)}
    written = {n: (wrong(p["answer"]) if n == 2 else p["answer"]) for n, p in probs.items() if n != 3}  # 3 left blank
    answers = {(probs[n]["page"], probs[n]["slot"]): t for n, t in written.items()}
    marks = {(probs[1]["page"], probs[1]["slot"], "stuck"): 1,
             (probs[4]["page"], probs[4]["slot"], "easy"): 1,
             (probs[6]["page"], probs[6]["slot"], "stuck"): 0.5}  # a tick, not a fill
    pages = [phone_scan(img, seed) for seed, img in enumerate(fill_in(config.day_dir(DATE, "timothy") / "packet.pdf", answers, marks))]
    pages = pages[::-1]                               # scanned in the wrong order
    pages[0] = pages[0].transpose(Image.ROTATE_180)   # and one page upside down
    scan = config.inbox_dir() / "timothy.pdf"
    scan.parent.mkdir(parents=True, exist_ok=True)
    to_pdf(pages, scan)
    return ws_id, probs, written, scan


def test_scan_grade_approve_and_scaffold(con, scanned):
    ws_id, probs, written, scan = scanned
    by_id = {str(p["id"]): n for n, p in probs.items()}
    asked = []

    def fake_reader(items):
        asked.extend(by_id[i["id"]] for i in items)
        return {i["id"]: {"text": written[by_id[i["id"]]], "confidence": 0.5 if by_id[i["id"]] == 5 else 0.97, "note": ""}
                for i in items}

    report = grade.grade_file(scan, transcribe=fake_reader)
    assert not any("!" in line for line in report), report

    # Blank detection and crop alignment: exactly the boxes we wrote in were sent to the reader.
    assert sorted(asked) == sorted(written)

    r = {row["number"]: row for row in db.results(con, ws_id)}
    assert r[3]["blank"] and not r[3]["correct"]
    assert not r[2]["correct"]
    assert all(r[n]["correct"] for n in probs if n not in (2, 3))
    assert r[1]["stuck"] and not r[1]["too_easy"]
    assert r[4]["too_easy"] and not r[4]["stuck"]
    assert "unclear 'stuck' mark" in r[6]["reason"]
    assert "low confidence" in r[5]["reason"]
    assert sum(bool(row["stuck"]) for row in r.values()) == 1
    assert sum(bool(row["too_easy"]) for row in r.values()) == 1
    assert not any(row["reason"] for n, row in r.items() if n not in (5, 6))

    ws = db.worksheet(con, ws_id)
    assert ws["status"] == "graded"
    folder = config.day_dir(DATE, "timothy")
    assert (folder / "scan.pdf").exists()
    assert len(json.loads((folder / "grades.json").read_text())["problems"]) == len(probs)

    # Approve: sessions are recorded per skill for new problems.
    levels.approve(con, ws_id)
    sessions = con.execute("SELECT * FROM session WHERE worksheet_id=?", (ws_id,)).fetchall()
    new = [p for p in probs.values() if p["kind"] == "new"]
    assert sum(s["n"] for s in sessions) == len(new)
    assert db.worksheet(con, ws_id)["status"] == "approved"

    # Next day: problem 1 was marked stuck -> worked example page + two scaffolded variants.
    next_id = planner.create(con, "timothy", NEXT)
    pages = json.loads(db.worksheet(con, next_id)["pages"])
    assert pages[0] == {"page": 1, "kind": "examples", "sources": [probs[1]["id"]]}
    scaffolds = [p for p in db.problems(con, next_id) if p["kind"] == "scaffold"]
    assert len(scaffolds) == 2 and all(p["source_problem_id"] == probs[1]["id"] for p in scaffolds)
    render.render(con, next_id, config.day_dir(NEXT, "timothy"))


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_live_transcription(con, scanned):
    """Real Claude read of the synthetic page (printed 'handwriting', so it should be near perfect)."""
    ws_id, probs, written, scan = scanned
    grade.grade_file(scan, transcribe=read.transcribe)
    rows = {r["number"]: r for r in db.results(con, ws_id)}
    matches = sum(grade.check(rows[n]["transcription"], text, "value" if "R" not in text else "remainder") is True
                  for n, text in written.items())
    assert matches >= 0.9 * len(written), {n: (rows[n]["transcription"], t) for n, t in written.items()}
