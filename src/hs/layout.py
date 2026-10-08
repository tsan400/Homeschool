"""Page geometry, in points (1/72 in) from the top-left of a US Letter page.

The renderer places everything at these coordinates and the scanner crops at
the same coordinates, so the two can't drift apart.
"""

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


FRENCH = (80, 750, 9)          # cx, cy, r: "did my French lesson" circle, bottom of page 1
FRENCH_QR = (104, 728, 44)     # x, y, size: opens the day's French lesson on a phone

# Page 1 opens with the word of the day on the left and the weather on the right, tucked
# under the QR code. Its problems start below them, a little closer together.
WORD = (40, 82, 380, 104)       # x, y, w, h
WEATHER = (440, 102, 132, 84)   # x, y, w, h
FIRST_TOP = max(WORD[1] + WORD[3], WEATHER[1] + WEATHER[3]) + 10

NARRATION_TOP, LINE_GAP = 200, 30  # writing lines on a narration page
NARRATION_HEAD = 98                # its heading starts this far above the first line
NARRATION_MIN_LINES = 8            # a chapter leaving room for this many lines on its last page
                                   # takes its narration there, not on a page of its own


def narration_after(text_end: float) -> float | None:
    """Where the writing lines start if the narration goes under a chapter whose text ends
    `text_end` points down its last page, or None if fewer than NARRATION_MIN_LINES fit there."""
    top = text_end + LINE_GAP + NARRATION_HEAD
    return top if (BODY_BOTTOM - top) / LINE_GAP > NARRATION_MIN_LINES - 1 else None


def narration_lines(pages: list[dict]) -> dict[int, float]:
    """{page: y of its first writing line} for each page a child narrates on: a narration page,
    or the last page of a chapter that ended high enough to share it."""
    return {pg["page"]: pg.get("lines_top", NARRATION_TOP) for pg in pages if pg["kind"] == "narration"}


def slot_h(slots: int, top: float = BODY_TOP) -> float:
    return (BODY_BOTTOM - top) / slots


def slots_below(top: float, per: int) -> int:
    """How many problems fit between `top` and the bottom of the page at nearly the usual spacing."""
    return max(0, int((BODY_BOTTOM - top) // (slot_h(per) * 0.95)))


def first_page_slots(per: int) -> int:
    """Problems on page 1, below the word and weather."""
    return max(1, slots_below(FIRST_TOP, per))


def slot_top(slot: int, slots: int, top: float = BODY_TOP) -> float:
    """Top of a problem's band. `slots` (problems on the page) and `top` (where they start) are
    stored with each packet page, so a packet always scans with the layout it was printed with."""
    if slots * (ANSWER_DY + ANSWER_H + 6) > BODY_BOTTOM - top:
        raise ValueError(f"{slots} problems per page don't fit")
    return top + (slot - 1) * slot_h(slots, top)


def answer_box(slot: int, slots: int, top: float = BODY_TOP) -> tuple[float, float, float, float]:
    """x, y, w, h of the answer box."""
    return ANSWER_X, slot_top(slot, slots, top) + ANSWER_DY, ANSWER_W, ANSWER_H


def bubble(slot: int, which: str, slots: int, top: float = BODY_TOP) -> tuple[float, float, float]:
    """cx, cy, r of a margin bubble ('stuck' or 'easy')."""
    return BUBBLE_X, slot_top(slot, slots, top) + BUBBLE_DY[which], BUBBLE_R


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
