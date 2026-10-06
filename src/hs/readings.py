"""History, science and French alongside math, following AmblesideOnline (content/ao/).

Each AO week has a history chapter, two science chapters and a nature-lore reading. They go out
in order, one subject per weekday (settings: ao.days), so a missed day just shifts the rest
along instead of skipping a reading. The reading is printed in the packet with a narration page
after it; the child tells it back, out loud or in writing. French is an audio lesson, done by ear
first in the Charlotte Mason way, with a checkbox on the packet.
"""

from datetime import date as Date
from functools import cache

import yaml

from hs import config

SUBJECTS = {"history": "History", "science": "Science", "nature": "Nature lore", "french": "French"}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@cache
def year(n: int) -> dict:
    path = config.CONTENT / "ao" / f"year{n}" / "readings.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else {"readings": []}


def years() -> list[int]:
    return sorted(int(p.name[4:]) for p in (config.CONTENT / "ao").glob("year*") if (p / "readings.yaml").exists())


def reading(rid: str) -> dict:
    for n in years():
        for r in year(n)["readings"]:
            if r["id"] == rid:
                return r | {"year": n}
    raise KeyError(rid)


def text(rid: str) -> str:
    r = reading(rid)
    return (config.CONTENT / "ao" / f"year{r['year']}" / "text" / f"{rid}.txt").read_text()


def next_reading(con, student, subject: str) -> dict | None:
    """The first reading in this subject the child hasn't been given yet."""
    given = {r["item"] for r in con.execute("""SELECT a.item FROM assignment a JOIN worksheet w ON w.id = a.worksheet_id
                                               WHERE w.student=? AND a.subject=?""", (student["id"], subject))}
    return next((r for r in year(student["ao_year"])["readings"] if r["stream"] == subject and r["id"] not in given), None)


def french_lesson(con, student) -> int:
    """Lessons move on only once one is marked done, so a missed day repeats the lesson."""
    done = con.execute("""SELECT COUNT(*) FROM assignment a JOIN worksheet w ON w.id = a.worksheet_id
                          WHERE w.student=? AND a.subject='french' AND a.done=1""", (student["id"],)).fetchone()[0]
    return done + 1


def plan(con, student, day: str) -> list[dict]:
    """The extra subjects for a daily packet: [{subject, item}], readings first, French last."""
    out = []
    if student["ao_year"]:
        subject = config.settings()["ao"]["days"].get(WEEKDAYS[Date.fromisoformat(day).weekday()])
        r = next_reading(con, student, subject) if subject else None
        if r:
            out.append({"subject": subject, "item": r["id"]})
    if student["french"]:
        out.append({"subject": "french", "item": f"lesson-{french_lesson(con, student)}"})
    return out


@cache
def french_course() -> dict:
    """The audio course named in settings (content/french/<course>.yaml): program and lessons."""
    return yaml.safe_load((config.CONTENT / "french" / f"{config.settings()['french']['course']}.yaml").read_text())


def lesson_info(item: str) -> dict:
    """"lesson-3" -> {n, program, title, url}; title and url are None past the course's end."""
    n = int(item.removeprefix("lesson-"))
    course = french_course()
    title, url = course["lessons"][n - 1] if n <= len(course["lessons"]) else (None, None)
    return {"n": n, "program": course["program"], "title": title, "url": url}


def french_label(item: str) -> str:
    f = lesson_info(item)
    return f"{f['program']}, lesson {f['n']}" + (f": {f['title']}" if f["title"] else "")
