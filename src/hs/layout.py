"""Page geometry, in points (1/72 in) from the top-left of a US Letter page.

The renderer places everything at these coordinates and the scanner crops at
the same coordinates, so the two can't drift apart.
"""

import math

PAGE_W, PAGE_H = 612, 792

# ArUco markers (4x4 dictionary, ids 0-3) in the corners, used to straighten scans.
MARKER = 36
MARKERS = {0: (24, 24), 1: (552, 24), 2: (24, 732), 3: (552, 732)}  # id -> top-left

QR = (468, 22, 76)  # x, y, size: just left of the top-right marker

BODY_TOP, BODY_BOTTOM = 112, 722  # problems are spaced evenly between these
LEGACY_SLOTS = 5   # packets printed before the per-packet setting existed had five per page

ANSWER_X, ANSWER_DY, ANSWER_W, ANSWER_H = 380, 18, 132, 58
BUBBLE_X, BUBBLE_R = 532, 9
BUBBLE_DY = {"stuck": 32, "easy": 70}


FRENCH = (80, 750, 9)  # cx, cy, r: "did my French lesson" circle, bottom of page 1

TODAY_H = 186           # weather and word of the day, at the top of page 1's body

NARRATION_TOP, LINE_GAP = 200, 30  # writing lines on a narration page


def slot_h(slots: int) -> float:
    return (BODY_BOTTOM - BODY_TOP) / slots


def today_slots(slots: int) -> int:
    """How many problem slots the page-1 weather and word panel takes up."""
    return math.ceil((TODAY_H + 8) / slot_h(slots))


def slot_top(slot: int, slots: int) -> float:
    """Top of a problem's band. `slots` is problems per page, stored with each packet page so a
    packet always scans with the layout it was printed with."""
    if slots * (ANSWER_DY + ANSWER_H + 6) > BODY_BOTTOM - BODY_TOP:
        raise ValueError(f"{slots} problems per page don't fit")
    return BODY_TOP + (slot - 1) * slot_h(slots)


def answer_box(slot: int, slots: int) -> tuple[float, float, float, float]:
    """x, y, w, h of the answer box."""
    return ANSWER_X, slot_top(slot, slots) + ANSWER_DY, ANSWER_W, ANSWER_H


def bubble(slot: int, which: str, slots: int) -> tuple[float, float, float]:
    """cx, cy, r of a margin bubble ('stuck' or 'easy')."""
    return BUBBLE_X, slot_top(slot, slots) + BUBBLE_DY[which], BUBBLE_R


def marker_corners(marker_id: int) -> list[tuple[float, float]]:
    """Corners in ArUco order: top-left, top-right, bottom-right, bottom-left."""
    x, y = MARKERS[marker_id]
    return [(x, y), (x + MARKER, y), (x + MARKER, y + MARKER), (x, y + MARKER)]


def qr_payload(ws_id: str, page: int) -> str:
    """Short on purpose: fewer characters means bigger QR modules, which read better from phone photos.
    Student and date come from the worksheet row."""
    return f"HS2|{ws_id}|{page}"


def parse_qr(text: str) -> dict | None:
    parts = (text or "").split("|")
    if len(parts) != 3 or parts[0] != "HS2" or not parts[2].isdigit():
        return None
    return {"worksheet": parts[1], "page": int(parts[2])}
