"""SQLite storage for families, children, levels and results. Content stays in plain files."""

import json
import sqlite3

from hs import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS family (
    id INTEGER PRIMARY KEY, name TEXT, key_wrapped BLOB NOT NULL, created_at TEXT,
    tz TEXT NOT NULL DEFAULT 'America/New_York');   -- "today" for printing and the calendar

CREATE TABLE IF NOT EXISTS parent (
    id INTEGER PRIMARY KEY, family_id INTEGER NOT NULL REFERENCES family(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL, created_at TEXT);

CREATE TABLE IF NOT EXISTS invite (         -- who may sign in; family_id NULL = starts a new family
    email TEXT PRIMARY KEY, family_id INTEGER REFERENCES family(id) ON DELETE CASCADE, created_at TEXT);

CREATE TABLE IF NOT EXISTS login_token (
    hash TEXT PRIMARY KEY, email TEXT, expires_at TEXT, used INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS student (
    id TEXT PRIMARY KEY,        -- e.g. "timothy-k3x9": unique across families, printed in QR codes
    family_id INTEGER NOT NULL REFERENCES family(id) ON DELETE CASCADE,
    name TEXT, grade INTEGER, math_grade INTEGER, created_at TEXT);

CREATE TABLE IF NOT EXISTS upload (
    id INTEGER PRIMARY KEY, family_id INTEGER NOT NULL REFERENCES family(id) ON DELETE CASCADE,
    filename TEXT, status TEXT,  -- queued | done | incomplete | error
    report TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS skill_level (
    student TEXT REFERENCES student(id) ON DELETE CASCADE, skill TEXT, level INTEGER NOT NULL DEFAULT 1,
    up_streak INTEGER NOT NULL DEFAULT 0, down_streak INTEGER NOT NULL DEFAULT 0,
    mastered INTEGER NOT NULL DEFAULT 0, last_seen TEXT, updated_at TEXT,
    PRIMARY KEY (student, skill));

CREATE TABLE IF NOT EXISTS worksheet (
    id TEXT PRIMARY KEY, student TEXT REFERENCES student(id) ON DELETE CASCADE, date TEXT, subject TEXT,
    kind TEXT,                  -- daily | placement | test
    status TEXT,                -- printed | partial | graded | approved
    pages TEXT,                 -- JSON list of {"page": n, "kind": "problems"|"examples"}
    scanned_pages TEXT NOT NULL DEFAULT '[]');  -- pages with a saved scan image

CREATE TABLE IF NOT EXISTS problem (
    id INTEGER PRIMARY KEY, worksheet_id TEXT REFERENCES worksheet(id) ON DELETE CASCADE,
    page INTEGER, slot INTEGER, number INTEGER, skill TEXT, level INTEGER,
    kind TEXT,                  -- new | review | scaffold | placement
    seed TEXT, prompt TEXT, answer TEXT, form TEXT, hint TEXT, steps TEXT,
    source_problem_id INTEGER); -- for scaffolds: the problem the child was stuck on

CREATE TABLE IF NOT EXISTS response (
    problem_id INTEGER PRIMARY KEY REFERENCES problem(id) ON DELETE CASCADE,
    transcription TEXT, confidence REAL, blank INTEGER,
    stuck INTEGER, too_easy INTEGER, stuck_fill REAL, easy_fill REAL,
    correct INTEGER, reason TEXT,          -- reason non-empty => needs review
    reviewed INTEGER NOT NULL DEFAULT 0, excluded INTEGER NOT NULL DEFAULT 0,
    scaffolded INTEGER NOT NULL DEFAULT 0, crop TEXT);  -- crop: vault file name

CREATE TABLE IF NOT EXISTS session (
    student TEXT REFERENCES student(id) ON DELETE CASCADE, skill TEXT, date TEXT, worksheet_id TEXT,
    n INTEGER, n_correct INTEGER, n_too_easy INTEGER, level_before INTEGER, level_after INTEGER,
    PRIMARY KEY (worksheet_id, skill));
"""


def connect() -> sqlite3.Connection:
    """One connection per thread/request. WAL lets the grading worker and web requests overlap."""
    config.home().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.db_path(), timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con


def student(con, sid):
    return con.execute("SELECT * FROM student WHERE id=?", (sid,)).fetchone()


def students(con, family_id) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM student WHERE family_id=? ORDER BY created_at, name", (family_id,)).fetchall()


def family_of_worksheet(con, ws_id) -> int | None:
    row = con.execute("SELECT s.family_id FROM worksheet w JOIN student s ON s.id = w.student WHERE w.id=?",
                      (ws_id,)).fetchone()
    return row["family_id"] if row else None


def levels(con, student) -> dict[str, sqlite3.Row]:
    rows = con.execute("SELECT * FROM skill_level WHERE student=?", (student,))
    return {r["skill"]: r for r in rows}


def worksheet(con, ws_id):
    return con.execute("SELECT * FROM worksheet WHERE id=?", (ws_id,)).fetchone()


def problems(con, ws_id, page=None):
    sql, args = "SELECT * FROM problem WHERE worksheet_id=?", [ws_id]
    if page is not None:
        sql, args = sql + " AND page=?", args + [page]
    return con.execute(sql + " ORDER BY number", args).fetchall()


def results(con, ws_id):
    """Problems joined with their responses (response columns are NULL if not yet scanned)."""
    return con.execute("""SELECT p.*, r.transcription, r.confidence, r.blank, r.stuck, r.too_easy,
            r.stuck_fill, r.easy_fill, r.correct, r.reason, r.reviewed, r.excluded, r.crop,
            r.problem_id IS NOT NULL AS scanned
        FROM problem p LEFT JOIN response r ON r.problem_id = p.id
        WHERE p.worksheet_id=? ORDER BY p.number""", (ws_id,)).fetchall()


def steps(row) -> list[str]:
    return json.loads(row["steps"] or "[]")
