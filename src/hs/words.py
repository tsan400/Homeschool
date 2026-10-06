"""Word of the day (content/words.yaml): one new word a day for each child, never repeated.

A child with a reading that day gets an unused word from the reading first, so the word turns
up again in the book. Every packet a child gets on the same day shares the same word.
"""

import re
from functools import cache

import yaml

from hs import config


@cache
def bands() -> dict[str, list[dict]]:
    raw = yaml.safe_load((config.CONTENT / "words.yaml").read_text())
    return {band: [dict(word=w, pos=p, meaning=m, sentence=s) for w, p, m, s in items] for band, items in raw.items()}


def band(grade: int) -> str:
    return "3-5" if grade <= 5 else "6-8"


def entry(word: str) -> dict:
    return next(e for items in bands().values() for e in items if e["word"] == word)


def appears(word: str, text: str) -> bool:
    stem = word[:-1] if word.endswith("e") else word
    return re.search(rf"\b(?:{re.escape(word)}|{re.escape(stem)})(?:s|es|d|ed|ing|ly)?\b", text, re.I) is not None


def pick(con, student, day: str, reading_text: str | None = None) -> dict:
    """-> entry, plus "in_reading": True when the word is in today's reading."""
    same_day = con.execute("""SELECT a.item FROM assignment a JOIN worksheet w ON w.id = a.worksheet_id
                              WHERE w.student=? AND w.date=? AND a.subject='word'""", (student["id"], day)).fetchone()
    words = bands()[band(student["grade"])]
    if same_day:
        e = entry(same_day["item"])
    else:
        used = [r["item"] for r in con.execute("""SELECT a.item FROM assignment a JOIN worksheet w ON w.id = a.worksheet_id
                                                  WHERE w.student=? AND a.subject='word' ORDER BY w.date""", (student["id"],))]
        fresh = [e for e in words if e["word"] not in used]
        if not fresh:  # the whole list has been used: start again with the longest-ago words
            fresh = sorted(words, key=lambda e: used.index(e["word"]) if e["word"] in used else -1)
        from_reading = [e for e in fresh if reading_text and appears(e["word"], reading_text)]
        e = (from_reading or fresh)[0]
    return e | {"in_reading": bool(reading_text) and appears(e["word"], reading_text)}
