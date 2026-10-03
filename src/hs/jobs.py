"""Uploaded scans are graded in the background, one at a time, so a slow handwriting read
never holds up a web request. The upload is saved encrypted first, so a restart just retries it."""

import threading
import traceback

from hs import accounts, db, grade, read, vault


def upload_name(upload_id: int) -> str:
    return f"uploads/{upload_id}"


def submit(con, family_id: int, filename: str, data: bytes) -> int:
    cur = con.execute("INSERT INTO upload (family_id, filename, status, report, created_at) VALUES (?,?,?,?,?)",
                      (family_id, filename, "queued", "", accounts.now()))
    con.commit()
    vault.put(con, family_id, upload_name(cur.lastrowid), data)
    return cur.lastrowid


def process(con, upload_id: int, transcribe=read.transcribe):
    up = con.execute("SELECT * FROM upload WHERE id=?", (upload_id,)).fetchone()
    try:
        data = vault.get(con, up["family_id"], upload_name(upload_id))
        report, complete = grade.grade_scan(con, up["family_id"], data, transcribe)
        status = "done" if complete else "incomplete"
    except Exception as e:  # keep the upload so it can be retried; show the parent what happened
        traceback.print_exc()
        report, status = [f"! grading failed: {e}"], "error"
    con.execute("UPDATE upload SET status=?, report=? WHERE id=?", (status, "\n".join(report), upload_id))
    con.commit()
    if status == "done":
        # The page images and crops are what the portal keeps; the raw upload is no longer needed.
        vault.delete(up["family_id"], upload_name(upload_id))


def retry(con, upload_id: int):
    con.execute("UPDATE upload SET status='queued', report='' WHERE id=?", (upload_id,))
    con.commit()


def run_queued(transcribe=read.transcribe) -> int:
    con = db.connect()
    n = 0
    while row := con.execute("SELECT id FROM upload WHERE status='queued' ORDER BY id LIMIT 1").fetchone():
        process(con, row["id"], transcribe)
        n += 1
    return n


class Worker:
    """A single background thread. `wake()` after each upload; it also drains the queue at start."""

    def __init__(self, transcribe=read.transcribe):
        self.transcribe = transcribe
        self.event = threading.Event()
        self.stop = False
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def start(self):
        self.event.set()
        self.thread.start()

    def wake(self):
        self.event.set()

    def loop(self):
        while not self.stop:
            self.event.wait(timeout=60)
            self.event.clear()
            try:
                run_queued(self.transcribe)
            except Exception:
                traceback.print_exc()

    def close(self):
        self.stop = True
        self.event.set()
