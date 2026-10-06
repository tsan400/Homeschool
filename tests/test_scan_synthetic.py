"""End to end: make a real packet, fill it in, 'phone scan' it, upload, grade, approve, plan the next day.

The offline tests swap the Claude reader for a stub that returns what we wrote, so they check
everything except handwriting recognition: markers, QR, alignment, crops, blank detection,
bubbles, grading, review flags, levels, stuck-problem scaffolding, and per-family storage.
Set ANTHROPIC_API_KEY to also run test_live_transcription against the real API.
"""

import json
import os

import pytest
from PIL import Image

from hs import accounts, config, db, grade, jobs, levels, packets, planner, read, render, vault
from synthetic import fill_in, phone_scan, to_pdf

DATE, NEXT = "2026-10-05", "2026-10-06"


def wrong(answer):
    return "999" if answer != "999" else "998"


@pytest.fixture
def scanned(con, family):
    fid, kids = family
    sid = kids["timothy"]
    ws_id = packets.make(con, sid, DATE)
    probs = {p["number"]: p for p in db.problems(con, ws_id)}
    written = {n: (wrong(p["answer"]) if n == 2 else p["answer"]) for n, p in probs.items() if n != 3}  # 3 left blank
    answers = {(probs[n]["page"], probs[n]["slot"]): t for n, t in written.items()}
    answers[probs[8]["page"], probs[8]["slot"]] = (written[8], 200)   # small, faint pencil still counts
    marks = {(probs[1]["page"], probs[1]["slot"], "stuck"): 1,
             (probs[4]["page"], probs[4]["slot"], "easy"): 1,
             (probs[7]["page"], probs[7]["slot"], "easy"): 0.5,     # a tick counts too
             (probs[6]["page"], probs[6]["slot"], "stuck"): 0.2}    # a stray dot is unclear
    packet = vault.get(con, fid, packets.packet_name(ws_id))
    pages = [phone_scan(img, seed) for seed, img in enumerate(fill_in(packet, answers, marks))]
    pages = pages[::-1]                               # scanned in the wrong order
    pages[0] = pages[0].transpose(Image.ROTATE_180)   # and one page upside down
    return fid, ws_id, probs, written, to_pdf(pages)


def reader_for(probs, written, asked=None, low=()):
    by_id = {str(p["id"]): n for n, p in probs.items()}

    def fake(items):
        if asked is not None:
            asked.extend(by_id[i["id"]] for i in items)
        return {i["id"]: {"text": written[by_id[i["id"]]], "confidence": 0.5 if by_id[i["id"]] in low else 0.97,
                          "note": ""} for i in items}
    return fake


def test_upload_grade_approve_and_scaffold(con, scanned):
    fid, ws_id, probs, written, scan_pdf = scanned
    asked = []
    uid = jobs.submit(con, fid, "timothy.pdf", scan_pdf)
    jobs.process(con, uid, reader_for(probs, written, asked, low=(5,)))
    up = con.execute("SELECT * FROM upload WHERE id=?", (uid,)).fetchone()
    assert up["status"] == "done" and "!" not in up["report"], up["report"]
    assert not vault.exists(fid, jobs.upload_name(uid))   # raw upload dropped once fully used
    assert_only_encrypted_files()

    # Blank detection and crop alignment: exactly the boxes we wrote in were sent to the reader.
    assert sorted(asked) == sorted(written)

    r = {row["number"]: row for row in db.results(con, ws_id)}
    assert r[3]["blank"] and not r[3]["correct"]
    assert not r[2]["correct"]
    assert all(r[n]["correct"] for n in probs if n not in (2, 3))
    assert r[1]["stuck"] and not r[1]["too_easy"]
    assert r[4]["too_easy"] and not r[4]["stuck"]
    assert r[7]["too_easy"]
    assert "unclear 'stuck' mark" in r[6]["reason"]
    assert "low confidence" in r[5]["reason"]
    assert sum(bool(row["stuck"]) for row in r.values()) == 1
    assert sum(bool(row["too_easy"]) for row in r.values()) == 2
    assert not any(row["reason"] for n, row in r.items() if n not in (5, 6))

    ws = db.worksheet(con, ws_id)
    assert ws["status"] == "graded"
    pages = json.loads(ws["scanned_pages"])
    assert pages == sorted({p["page"] for p in probs.values()})
    assert vault.get(con, fid, grade.page_name(ws_id, pages[0])).startswith(b"\xff\xd8")   # page image for the calendar
    assert vault.get(con, fid, r[1]["crop"]).startswith(b"\x89PNG")

    # Approve: sessions are recorded per skill for new problems.
    levels.approve(con, ws_id)
    sessions = con.execute("SELECT * FROM session WHERE worksheet_id=?", (ws_id,)).fetchall()
    new = [p for p in probs.values() if p["kind"] == "new"]
    assert sum(s["n"] for s in sessions) == len(new)
    assert db.worksheet(con, ws_id)["status"] == "approved"

    # Next day: problem 1 was marked stuck -> worked example page + two scaffolded variants.
    next_id = packets.make(con, ws["student"], NEXT)
    pages = json.loads(db.worksheet(con, next_id)["pages"])
    assert pages[0] == {"page": 1, "kind": "examples", "sources": [probs[1]["id"]], "today": True}
    scaffolds = [p for p in db.problems(con, next_id) if p["kind"] == "scaffold"]
    assert len(scaffolds) == 2 and all(p["source_problem_id"] == probs[1]["id"] for p in scaffolds)


def test_another_familys_upload_is_refused(con, scanned):
    fid, ws_id, probs, written, scan_pdf = scanned
    other = accounts.create_family(con, "Other")
    uid = jobs.submit(con, other, "stolen.pdf", scan_pdf)
    jobs.process(con, uid, reader_for(probs, written))
    up = con.execute("SELECT * FROM upload WHERE id=?", (uid,)).fetchone()
    assert up["status"] == "incomplete" and "didn't print" in up["report"]
    assert db.worksheet(con, ws_id)["status"] == "printed"
    assert not any(r["scanned"] for r in db.results(con, ws_id))


def test_failed_grading_keeps_the_upload_for_retry(con, scanned):
    fid, ws_id, probs, written, scan_pdf = scanned

    def broken_reader(items):
        raise ConnectionError("API unavailable")

    uid = jobs.submit(con, fid, "timothy.pdf", scan_pdf)
    jobs.process(con, uid, broken_reader)
    up = con.execute("SELECT * FROM upload WHERE id=?", (uid,)).fetchone()
    assert up["status"] == "error" and "API unavailable" in up["report"]
    assert vault.exists(fid, jobs.upload_name(uid))
    assert_only_encrypted_files()

    jobs.retry(con, uid)
    assert jobs.run_queued(reader_for(probs, written)) == 1
    assert con.execute("SELECT status FROM upload WHERE id=?", (uid,)).fetchone()["status"] == "done"
    assert db.worksheet(con, ws_id)["status"] == "graded"


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_live_transcription(con, scanned):
    """Real Claude read of the synthetic page (printed 'handwriting', so it should be near perfect)."""
    fid, ws_id, probs, written, scan_pdf = scanned
    grade.grade_scan(con, fid, scan_pdf, read.transcribe)
    rows = {r["number"]: r for r in db.results(con, ws_id)}
    matches = sum(grade.check(rows[n]["transcription"], text, "value" if "R" not in text else "remainder") is True
                  for n, text in written.items())
    assert matches >= 0.9 * len(written), {n: (rows[n]["transcription"], t) for n, t in written.items()}


def assert_only_encrypted_files():
    """Everything the portal keeps on disk, apart from the database, is encrypted."""
    for f in config.files_dir().rglob("*"):
        if f.is_file():
            head = f.read_bytes()[:64]
            assert head.startswith(vault.MAGIC), f"unencrypted file at rest: {f}"
            assert b"PNG" not in head and b"%PDF" not in head and b"JFIF" not in head
    stray = [f for f in config.home().iterdir() if f.is_file() and not f.name.startswith("hs.db")]
    assert not stray, stray



def test_packets_keep_the_layout_they_were_printed_with(con, family):
    """A packet printed with five problems per page (before the setting existed) still scans
    after the default changes."""
    fid, kids = family
    ws_id = packets.make(con, kids["hannah"], DATE)
    pages = json.loads(db.worksheet(con, ws_id)["pages"])
    for pg in pages:
        pg.pop("slots", None)                       # what an old packet row looks like
    con.execute("UPDATE worksheet SET pages=? WHERE id=?", (json.dumps(pages), ws_id))
    con.execute("UPDATE problem SET page = 1 + (number - 1) / 5, slot = 1 + (number - 1) % 5 WHERE worksheet_id=?", (ws_id,))
    con.commit()
    probs = {p["number"]: p for p in db.problems(con, ws_id)}
    packet, _ = render.render(con, ws_id)
    vault.put(con, fid, packets.packet_name(ws_id), packet)
    answers = {(p["page"], p["slot"]): p["answer"] for p in probs.values()}
    scan_pdf = to_pdf([phone_scan(img, i) for i, img in enumerate(fill_in(packet, answers, {}, slots=5))])
    report, complete = grade.grade_scan(con, fid, scan_pdf, reader_for(probs, {n: p["answer"] for n, p in probs.items()}))
    assert complete, report
    assert all(r["correct"] for r in db.results(con, ws_id))
