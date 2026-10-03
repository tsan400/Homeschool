"""Page geometry, in points (1/72 in) from the top-left of a US Letter page.

The renderer places everything at these coordinates and the scanner crops at
the same coordinates, so the two can't drift apart.
"""

PAGE_W, PAGE_H = 612, 792

# ArUco markers (4x4 dictionary, ids 0-3) in the corners, used to straighten scans.
MARKER = 36
MARKERS = {0: (24, 24), 1: (552, 24), 2: (24, 732), 3: (552, 732)}  # id -> top-left

QR = (468, 22, 76)  # x, y, size: just left of the top-right marker

BODY_TOP, SLOT_H, SLOTS = 112, 122, 5  # five problems per page

ANSWER_X, ANSWER_DY, ANSWER_W, ANSWER_H = 380, 18, 132, 58
BUBBLE_X, BUBBLE_R = 532, 9
BUBBLE_DY = {"stuck": 32, "easy": 70}


def slot_top(slot: int) -> float:
    return BODY_TOP + (slot - 1) * SLOT_H


def answer_box(slot: int) -> tuple[float, float, float, float]:
    """x, y, w, h of the answer box."""
    return ANSWER_X, slot_top(slot) + ANSWER_DY, ANSWER_W, ANSWER_H


def bubble(slot: int, which: str) -> tuple[float, float, float]:
    """cx, cy, r of a margin bubble ('stuck' or 'easy')."""
    return BUBBLE_X, slot_top(slot) + BUBBLE_DY[which], BUBBLE_R


def marker_corners(marker_id: int) -> list[tuple[float, float]]:
    """Corners in ArUco order: top-left, top-right, bottom-right, bottom-left."""
    x, y = MARKERS[marker_id]
    return [(x, y), (x + MARKER, y), (x + MARKER, y + MARKER), (x, y + MARKER)]


def qr_payload(student: str, date: str, ws_id: str, page: int) -> str:
    return f"HS1|{student}|{date}|{ws_id}|{page}"


def parse_qr(text: str) -> dict | None:
    parts = (text or "").split("|")
    if len(parts) != 5 or parts[0] != "HS1":
        return None
    return {"student": parts[1], "date": parts[2], "worksheet": parts[3], "page": int(parts[4])}
