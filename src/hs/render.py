"""Builds packet and answer-key PDFs with Typst. All placement uses layout.py coordinates.

Look: quiet and friendly, in black and white. Nunito for words, New Computer Modern for math,
Literata for readings; light gray only for small labels, number badges and rules. Anything the scanner reads
(answer boxes, circles, writing lines) stays plain dark-on-white at the coordinates in layout.py.
"""

import json
import re
import tempfile
from datetime import date as Date
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
import segno
import typst

from hs import config, db, layout as L, readings, words

FONT_DIR = Path(__file__).parent / "fonts"
FONTS = '("Nunito", "DejaVu Sans")'
READING_X = 70  # side margins of a reading's text
INK, MUTED, HAIR, LINE = "#1a1a1a", "#6b6b6b", "#d4d4d4", "#333333"
# One accent per subject. Black and white for now; a colour here shows up in that subject's
# labels, badges and rules.
ACCENT = dict.fromkeys(("math", "history", "science", "nature", "french", "word"), INK)
HEADER = f"""#set page(width: {L.PAGE_W}pt, height: {L.PAGE_H}pt, margin: 0pt)
#set text(font: {FONTS}, size: 16pt, fill: rgb("{INK}"))
#show math.equation: set text(font: "New Computer Modern Math")
"""


def col(hex_: str) -> str:
    return f'rgb("{hex_}")'


def tint(hex_: str, amount: int = 92) -> str:
    return f'rgb("{hex_}").lighten({amount}%)'


def esc(text: str) -> str:
    """Escape plain text for Typst markup."""
    for ch in "\\#$*_`<>@[]~":
        text = text.replace(ch, "\\" + ch)
    return text


def big(markup: str) -> str:
    """Display-size math so fractions are full height, kept on one line:
    $1/2$ -> #box[$display(1/2)$]."""
    return re.sub(r"(?<!\\)\$([^$]+?)(?<!\\)\$", r"#box[$display(\1)$]", markup)


def at(x, y, body: str) -> str:
    return f"#place(top + left, dx: {x}pt, dy: {y}pt)[{body}]\n"


def marker_svg(marker_id: int) -> str:
    bits = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), marker_id, 6)
    cells = "".join(f'<rect x="{x}" y="{y}" width="1" height="1"/>'
                    for y in range(6) for x in range(6) if bits[y, x] < 128)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 6 6" shape-rendering="crispEdges">{cells}</svg>'


# ---------- QR code: rounded, joined modules and rounded corner squares ----------

def _rrect(x, y, w, h, r) -> str:
    return (f"M{x + r} {y}H{x + w - r}A{r} {r} 0 0 1 {x + w} {y + r}V{y + h - r}A{r} {r} 0 0 1 {x + w - r} {y + h}"
            f"H{x + r}A{r} {r} 0 0 1 {x} {y + h - r}V{y + r}A{r} {r} 0 0 1 {x + r} {y}Z")


def qr_svg(payload: str, border: int = 2, error: str = "m") -> str:
    """A QR code with soft, rounded shapes. Readers only need the corner squares' 1:1:3:1:1
    stripes and each module's centre, and rounding keeps both."""
    matrix = segno.make(payload, error=error).matrix
    n = len(matrix)

    def corner(x, y):  # the three big squares, drawn separately
        return (x < 7 and y < 7) or (x >= n - 7 and y < 7) or (x < 7 and y >= n - 7)

    def dark(x, y):
        return 0 <= x < n and 0 <= y < n and matrix[y][x] and not corner(x, y)

    dots = []  # every subpath clockwise, so overlaps join instead of cancelling
    for y in range(n):
        for x in range(n):
            if dark(x, y):
                dots.append(f"M{x} {y + .5}a.5 .5 0 1 1 1 0a.5 .5 0 1 1 -1 0Z")
                if dark(x + 1, y):
                    dots.append(f"M{x + .5} {y}h1v1h-1Z")
                if dark(x, y + 1):
                    dots.append(f"M{x} {y + .5}h1v1h-1Z")
    # Corner radius of one module: rounder corners make OpenCV misplace the code's corners.
    eyes = "".join(_rrect(cx, cy, 7, 7, 1) + _rrect(cx + 1, cy + 1, 5, 5, 0.6) + _rrect(cx + 2, cy + 2, 3, 3, 0.6)
                   for cx, cy in ((0, 0), (n - 7, 0), (0, n - 7)))
    size = n + 2 * border
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
            f'<rect width="{size}" height="{size}" fill="#fff"/><g transform="translate({border} {border})" fill="#000">'
            f'<path d="{"".join(dots)}"/><path fill-rule="evenodd" d="{eyes}"/></g></svg>')


# ---------- weather icons: chunky, friendly shapes with little faces, in black and white ----------

SOFT, CHEEK = "#ececec", "#d2d2d2"
OUTLINE = 2.3
CLOUD = [("rect", 8, 25, 33, 11, 5.5), ("circle", 15, 26, 6.5), ("circle", 24, 20, 9), ("circle", 33.5, 25, 7)]


def _shape(sh, grow=0.0) -> str:
    kind, *a = sh
    if kind == "circle":
        cx, cy, r = a
        return f'<circle cx="{cx}" cy="{cy}" r="{r + grow}"/>'
    x, y, w, h, r = a
    return f'<rect x="{x - grow}" y="{y - grow}" width="{w + 2 * grow}" height="{h + 2 * grow}" rx="{r + grow}"/>'


def _blob(shapes, fill) -> str:
    """Overlapping shapes drawn as one outlined blob: the same shapes a little bigger in ink
    underneath, then filled on top, so there are no seams where they overlap."""
    return (f'<g fill="{INK}">' + "".join(_shape(sh, OUTLINE) for sh in shapes) + "</g>"
            f'<g fill="{fill}">' + "".join(_shape(sh) for sh in shapes) + "</g>")


def _face(cx, cy, eyes="open", mouth="smile", s=1.0) -> str:
    dx, line = 3.6 * s, f'fill="none" stroke="{INK}" stroke-width="{1.6 * s:.2f}" stroke-linecap="round"'
    if eyes == "open":
        out = "".join(f'<circle cx="{cx + d:.2f}" cy="{cy:.2f}" r="{1.5 * s:.2f}" fill="{INK}"/>' for d in (-dx, dx))
    else:  # sleepy: closed eyes
        out = "".join(f'<path d="M{cx + d - 1.7 * s:.2f} {cy - .4 * s:.2f} q{1.7 * s:.2f} {1.8 * s:.2f} {3.4 * s:.2f} 0" {line}/>'
                      for d in (-dx, dx))
    if mouth == "smile":
        out += f'<path d="M{cx - 2.4 * s:.2f} {cy + 3.2 * s:.2f} q{2.4 * s:.2f} {2.4 * s:.2f} {4.8 * s:.2f} 0" {line}/>'
    else:  # a little "oh!"
        out += f'<circle cx="{cx:.2f}" cy="{cy + 4 * s:.2f}" r="{1.3 * s:.2f}" {line}/>'
    return out


def _sun(cx, cy, r, rays=range(8), face=True) -> str:
    import math
    out = f'<g stroke="{INK}" stroke-width="2.4" stroke-linecap="round">'
    for i in rays:  # alternating long and short rays
        a, length = i * math.pi / 4, (5 if i % 2 == 0 else 3.4)
        c, s_ = math.cos(a), math.sin(a)
        out += (f'<line x1="{cx + (r + 4) * c:.2f}" y1="{cy + (r + 4) * s_:.2f}" '
                f'x2="{cx + (r + 4 + length) * c:.2f}" y2="{cy + (r + 4 + length) * s_:.2f}"/>')
    out += "</g>" + _blob([("circle", cx, cy, r)], "#ffffff")
    if face:
        out += (f'<circle cx="{cx - r * .62:.2f}" cy="{cy + r * .3:.2f}" r="{r * .17:.2f}" fill="{CHEEK}"/>'
                f'<circle cx="{cx + r * .62:.2f}" cy="{cy + r * .3:.2f}" r="{r * .17:.2f}" fill="{CHEEK}"/>'
                + _face(cx, cy - r * .12, s=r / 10))
    return out


def _drop(x, y, s=1.0) -> str:
    return (f'<path transform="translate({x} {y}) scale({s})" fill="{INK}" '
            'd="M0 -4.6 C2.6 -1.4 3.4 0.4 3.4 1.6 A3.4 3.4 0 0 1 -3.4 1.6 C-3.4 0.4 -2.6 -1.4 0 -4.6 Z"/>')


def _flake(x, y) -> str:
    arms = "".join(f'<line x1="{-3.4 * c:.2f}" y1="{-3.4 * s:.2f}" x2="{3.4 * c:.2f}" y2="{3.4 * s:.2f}"/>'
                   for c, s in ((1, 0), (.5, .866), (-.5, .866)))
    return f'<g transform="translate({x} {y})" stroke="{INK}" stroke-width="1.8" stroke-linecap="round">{arms}</g>'


def weather_svg(icon: str) -> str:
    up = 'transform="translate(0 -6)"'
    if icon == "sun":
        body = _sun(24, 24, 10)
    elif icon == "partly":
        body = (_sun(16.5, 16, 7, rays=(3, 4, 5, 6, 7), face=False)
                + f'<g transform="translate(7 9) scale(0.82)">{_blob(CLOUD, SOFT)}{_face(24, 28)}</g>')
    elif icon == "cloud":
        body = _blob(CLOUD, SOFT) + _face(24, 28, eyes="sleepy")
    elif icon == "fog":
        waves = "".join(f'<path d="M{x0} {y} q4 -3 8 0 t8 0 t8 0" fill="none" stroke="{INK}" stroke-width="2.2" stroke-linecap="round"/>'
                        for x0, y in ((10, 39.5), (14, 45)))
        body = f"<g {up}>{_blob(CLOUD, SOFT)}{_face(24, 28, eyes='sleepy')}</g>" + waves
    elif icon == "storm":
        body = (f"<g {up}>{_blob(CLOUD, SOFT)}{_face(24, 27.5, mouth='oh')}</g>"
                f'<polygon points="25.5,31 18.5,40.5 23.5,40.5 20.5,47.5 30.5,36 25.5,36 28.5,31" fill="{INK}" '
                f'stroke="{INK}" stroke-width="1.2" stroke-linejoin="round"/>')
    else:
        below = {"rain": _drop(15.5, 39.5) + _drop(24, 42.5) + _drop(32.5, 39.5),
                 "drizzle": _drop(18, 41, .7) + _drop(30, 41, .7),
                 "snow": _flake(15.5, 40.5) + _flake(24, 44) + _flake(32.5, 40.5)}[icon]
        body = f"<g {up}>{_blob(CLOUD, SOFT)}{_face(24, 28)}</g>" + below
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">{body}</svg>'


# ---------- pieces of a page ----------

def pretty_date(iso: str) -> str:
    d = Date.fromisoformat(iso)
    return d.strftime("%A, %B ") + str(d.day) + d.strftime(", %Y")


def chip(label: str, accent: str) -> str:
    """The subject tag next to the name (Typst code, not markup)."""
    return (f"box(fill: {tint(accent)}, inset: (x: 7pt, y: 4pt), radius: 8pt)"
            f"[#text(size: 8.5pt, weight: 800, tracking: 0.7pt, fill: {col(accent)})[{esc(label.upper())}]]")


def page_frame(ws, page, total: int, student_name: str, label: str, accent: str) -> str:
    """Markers, QR code, header and page number on every page. `page` is a number, or Typst code
    for one (reading pages flow, so their number is only known while Typst lays them out)."""
    out = "".join(at(x, y, f'#image("m{i}.svg", width: {L.MARKER}pt)') for i, (x, y) in L.MARKERS.items())
    qr = f'"qr{page}.svg"' if isinstance(page, int) else f'"qr" + str({page}) + ".svg"'
    out += at(L.QR[0], L.QR[1], f"#image({qr}, width: {L.QR[2]}pt)")
    out += at(76, 26, f"#grid(columns: 2, column-gutter: 9pt, align: horizon, "
                      f"text(size: 22pt, weight: 800)[{esc(student_name)}], {chip(label, accent)})")
    out += at(76, 57, f"#text(size: 11pt, fill: {col(MUTED)})[{pretty_date(ws['date'])}]")
    number = page if isinstance(page, int) else f"#{page}"
    out += at(0, 745, f"#box(width: 540pt)[#align(right)[#text(size: 9pt, fill: {col(MUTED)})[Page {number} of {total}]]]")
    return out


def label(text: str) -> str:
    return f"#text(size: 8pt, weight: 800, tracking: 1pt, fill: {col(MUTED)})[{esc(text)}]"


def word_card(word: dict) -> str:
    """Word of the day, top left of page 1."""
    accent = ACCENT["word"]
    tag = f"text(size: 7.5pt, style: \"italic\", fill: {col(MUTED)})[look for it in today's reading]" if word.get("in_reading") else "[]"
    return (f"#stack(spacing: 7pt, grid(columns: (1fr, auto), align: horizon, [{label('WORD OF THE DAY')}], {tag}), "
            f"[#text(size: 24pt, weight: 800, fill: {col(accent)})[{esc(word['word'])}] #h(5pt) "
            f"#text(size: 11pt, style: \"italic\", fill: {col(MUTED)})[{esc(word['pos'])}]], "
            f"[#text(size: 11.5pt)[{esc(word['meaning'])}]], "
            f"[#text(font: \"Literata\", size: 11pt, style: \"italic\")[“{esc(word['sentence'])}”]])")


def weather_card(w: dict) -> str:
    """The day's weather, top right of page 1, under the QR code."""
    temps = f"#text(fill: {col(MUTED)})[High] *{w['high']}°* #h(3pt) #text(fill: {col(MUTED)})[Low] *{w['low']}°*"
    return (f"#stack(spacing: 6pt, [{label('WEATHER')}], "
            f"grid(columns: (32pt, 1fr), column-gutter: 7pt, align: horizon, image(\"w-{w['icon']}.svg\", width: 32pt), "
            f"stack(spacing: 4pt, [#text(size: 11.5pt, weight: 800)[{esc(w['sky'])}]], [#text(size: 9.5pt)[{temps}]])), "
            f"[#text(size: 8.5pt)[{esc(w['notes'][0])}]], "
            f"[#text(size: 7.5pt, fill: {col(MUTED)})[sunrise {w['sunrise']} · sunset {w['sunset']}]])")


def today_panel(word: dict, forecast: dict | None) -> str:
    """Page 1's opening: the word of the day on the left, the weather on the right."""
    x, y, w, h = L.WORD
    out = at(x, y, f"#block(width: {w}pt, height: {h}pt, stroke: 0.75pt + {col(HAIR)}, radius: 10pt, "
                   f"inset: (x: 14pt, y: 11pt), clip: true)[#align(horizon)[{word_card(word)}]]")
    if forecast:
        x, y, w, h = L.WEATHER
        out += at(x, y, f"#block(width: {w}pt, height: {h}pt, clip: true)[{weather_card(forecast)}]")
    return out


def number_badge(n: int, accent: str) -> str:
    return (f"#box(width: 22pt, height: 22pt, radius: 11pt, fill: {tint(accent)})"
            f"[#align(center + horizon)[#text(size: 11pt, weight: 800, fill: {col(accent)})[{n}]]]")


def problem_slot(p, slots: int, start: float = L.BODY_TOP) -> str:
    top = L.slot_top(p["slot"], slots, start)
    x, y, w, h = L.answer_box(p["slot"], slots, start)
    out = at(40, top, f"#line(length: {L.PAGE_W - 80}pt, stroke: 0.6pt + {col(HAIR)})")
    out += at(34, top + 15, number_badge(p["number"], ACCENT["math"]))
    out += at(66, top + 16, f'#block(width: 300pt)[#set text(size: 18pt)\n{big(p["prompt"])}]')
    out += at(x + 2, y - 12, f"#text(size: 8pt, fill: {col(MUTED)})[Answer]")
    out += at(x, y, f"#rect(width: {w}pt, height: {h}pt, stroke: 1.1pt + {col(LINE)}, radius: 7pt)")
    for which, text in (("stuck", "stuck"), ("easy", "too easy")):
        cx, cy, r = L.bubble(p["slot"], which, slots, start)
        out += at(cx - r, cy - r, f"#circle(radius: {r}pt, stroke: 1pt + {col(LINE)})")
        out += at(cx + r + 4, cy - 6, f"#text(size: 9pt, fill: {col(MUTED)})[{text}]")
    return out


EXAMPLES_W = L.PAGE_W - 112


def examples_height(con, ids: list[int]) -> float:
    """How tall the worked examples come out, so problems can start right below them."""
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        compile_typ(f"#set page(width: {EXAMPLES_W}pt, height: auto, margin: 0pt)\n"
                    f"#set text(font: {FONTS}, size: 16pt, fill: rgb(\"{INK}\"))\n"
                    "#show math.equation: set text(font: \"New Computer Modern Math\")\n"
                    + examples_block(con, ids), build, build / "h.pdf")
        return pdfium.PdfDocument((build / "h.pdf").read_bytes())[0].get_size()[1]


def examples_page(con, ids: list[int], top: float) -> str:
    return at(56, top, examples_block(con, ids))


def examples_block(con, ids: list[int]) -> str:
    body = [f"[#text(size: 17pt, weight: 800, fill: {col(ACCENT['math'])})[Let's look again]]",
            f"[#text(size: 10.5pt, fill: {col(MUTED)})[You marked these as stuck. Read each example, then try the practice problems in this packet.]]"]
    for pid in ids:
        p = con.execute("SELECT p.*, w.date FROM problem p JOIN worksheet w ON w.id = p.worksheet_id WHERE p.id=?", (pid,)).fetchone()
        steps = "\n".join(f"+ {big(s)}" for s in db.steps(p))
        body.append(f"[#line(length: 100%, stroke: 0.6pt + {col(HAIR)})\n#set text(size: 13pt)\n"
                    f"*Problem {p['number']} from {pretty_date(p['date'])}:* {big(p['prompt'])}\n\n{steps}\n\n"
                    f"*Answer:* {esc(p['answer'])}]")
    return f"#block(width: {EXAMPLES_W}pt)[#stack(spacing: 10pt, {', '.join(body)})]"


def reading_body(r: dict, accent: str) -> str:
    chapter, _, title = r["title"].partition(": ")
    if not title:
        chapter, title = "", r["title"]
    meta = " · ".join(x for x in (r["book"], chapter, f"AO Year {r['year']}, week {r['week']}") if x)
    # A block, not paragraphs, so the book's first-line indent doesn't reach the heading.
    out = [f"#block(below: 14pt)[#set par(first-line-indent: 0pt, justify: false, leading: 0.45em)\n#stack(spacing: 8pt, "
           f"[#text(font: \"Nunito\", size: 8.5pt, weight: 800, tracking: 0.8pt, fill: {col(accent)})[{esc(meta.upper())}]], "
           f"[#text(font: \"Nunito\", size: 20pt, weight: 800, fill: {col(INK)})[{esc(title)}]], "
           f"line(length: 36pt, stroke: 2pt + {col(accent)}))]"]
    for para in readings.text(r["id"]).strip().split("\n\n"):
        if para.startswith("## "):
            out.append(f"#v(6pt)\n#text(font: \"Nunito\", size: 13pt, weight: 800)[{esc(para[3:])}]")
        elif para.startswith("> "):
            out.append("#pad(left: 2em)[#emph[" + " \\\n".join(esc(ln[2:]) for ln in para.split("\n")) + "]]")
        else:
            out.append(esc(para))
    return "\n\n".join(out)


def reading_section(r: dict, accent: str, frame: str = "") -> str:
    """A reading set as flowing book text, over as many pages as it needs."""
    return (f"#page(margin: (top: 104pt, bottom: 82pt, x: {READING_X}pt), background: {frame or 'none'})[\n"
            "#set text(font: \"Literata\", size: 12.5pt)\n"
            "#set par(justify: true, leading: 0.68em, spacing: 0.75em, first-line-indent: 1.2em)\n"
            + reading_body(r, accent) + "\n]\n")


def text_end(page) -> float:
    """How far down a laid-out page (pdfium, drawn without its frame) the text reaches, in points."""
    ink = np.where((np.array(page.render(scale=1, grayscale=True).to_pil().convert("L")) < 200).any(axis=1))[0]
    return float(ink.max() + 1) if ink.size else 0.0


def narration_page(r: dict, accent: str, top: float = L.NARRATION_TOP, x: float = 56) -> str:
    """"Tell it back" and the writing lines: a page of their own, or (with `top` and `x`) under
    a chapter that ended high on its last page."""
    title = r["title"].partition(": ")[2] or r["title"]
    w = L.PAGE_W - 2 * x
    out = at(x, top - L.NARRATION_HEAD, f"#block(width: {w}pt)[#stack(spacing: 8pt, "
                      f"[#text(size: 17pt, weight: 800)[Tell it back]], "
                      f"[#text(size: 12pt)[#text(weight: 700, fill: {col(accent)})[{esc(r['book'])}] · {esc(title)}]], "
                      f"[#text(size: 10pt, fill: {col(MUTED)})[Tell what you read in your own words. Say it out loud to a parent, "
                      f"or write it on the lines: who, where, what happened first and next. You may draw a picture too.]])]")
    y = top
    while y < L.BODY_BOTTOM:
        out += at(x, y, f"#line(length: {w}pt, stroke: 0.6pt + rgb(\"#a3abb4\"))")
        y += L.LINE_GAP
    return out


def french_box(item: str) -> str:
    """Foot of page 1: a circle to fill in, a QR code that opens the lesson, and its name."""
    cx, cy, r = L.FRENCH
    f = readings.lesson_info(item)
    out = at(cx - r, cy - r, f"#circle(radius: {r}pt, stroke: 1pt + {col(LINE)})")
    x = cx + r + 8
    if f["url"]:
        qx, qy, qs = L.FRENCH_QR
        out += at(qx, qy, f'#image("fr.svg", width: {qs}pt)')
        x = qx + qs + 9
    lesson = f"Lesson {f['n']}" + (f": {esc(f['title'])}" if f["title"] else "")
    how = "Scan the code to listen. " if f["url"] else ""
    return out + at(x, 731, f"#stack(spacing: 4.5pt, "
                            f"[#text(size: 10pt)[#text(weight: 800, fill: {col(ACCENT['french'])})[French] #h(3pt) {esc(f['program'])}]], "
                            f"[#text(size: 10pt)[{lesson}]], "
                            f"[#text(size: 8pt, fill: {col(MUTED)})[{how}Fill in the circle when you're done.]])")


def also_today(extras, word: dict | None, forecast: dict | None) -> str:
    """Parent's notes for the key: the word, the reading and the French lesson."""
    lines = []
    if word:
        lines.append(f"- *Word of the day:* {esc(word['word'])} ({esc(word['pos'])}): {esc(word['meaning'])} "
                     f"Ask them to use it in a sentence of their own today.")
    for subject, a in extras.items():
        if subject == "french":
            name = readings.french_label(a["item"])
            lines.append(f"- *French:* {esc(name)}{'' if name[-1] in '?!.' else '.'} Listen and repeat out loud; no reading or spelling yet.")
        elif subject in readings.SUBJECTS:
            r = readings.reading(a["item"])
            lines.append(f"- *{readings.SUBJECTS[subject]}:* {esc(r['book'])}, {esc(r['title'])} (AO Year {r['year']}, week {r['week']}). "
                         "Read it once, then ask: \"Tell me what you read.\" Let them finish before you correct anything.")
    if forecast:
        lines.append(f"- *Weather:* {esc(forecast['sky'])}, high {forecast['high']}°, low {forecast['low']}°. "
                     + " ".join(esc(n) for n in forecast["notes"]))
    return "#v(12pt)\n== Also today\n" + "\n".join(lines) if lines else ""


def compile_typ(source: str, build: Path, out: Path):
    (build / "main.typ").write_text(source)
    typst.compile(str(build / "main.typ"), output=str(out), root=str(build), font_paths=[str(FONT_DIR)])


def number_pages(con, ws, build: Path) -> list[dict]:
    """Readings flow over however many pages they need, so count them (by laying each one out on
    its own) and give every page its final number. Math pages come first and keep theirs.
    A chapter that ends high on its last page takes its narration lines there, under the text,
    instead of on a page of their own."""
    pages, room = [pg for pg in json.loads(ws["pages"]) if pg["kind"] in ("examples", "problems")], None
    for pg in json.loads(ws["pages"]):
        if pg["kind"] == "reading":
            compile_typ(HEADER + reading_section(readings.reading(pg["item"]), ACCENT[pg["subject"]]), build, build / "count.pdf")
            doc = pdfium.PdfDocument((build / "count.pdf").read_bytes())
            room = L.narration_after(text_end(doc[len(doc) - 1]))
            pages.append(pg | {"page": len(pages) + 1, "pages": len(doc)})
        elif pg["kind"] == "narration":
            last = pages[-1]["page"] + pages[-1]["pages"] - 1
            pg = {k: v for k, v in pg.items() if k != "lines_top"}
            pg |= {"page": last, "lines_top": room} if room else {"page": last + 1}
            pages.append(pg)
            con.execute("UPDATE assignment SET page=? WHERE worksheet_id=? AND subject=?", (pg["page"], ws["id"], pg["subject"]))
    con.execute("UPDATE worksheet SET pages=? WHERE id=?", (json.dumps(pages), ws["id"]))
    con.commit()
    return pages


def todays_word(con, ws, extras) -> dict | None:
    if "word" not in extras:
        return None
    reading = next((readings.text(a["item"]) for s, a in extras.items() if s in ("history", "science", "nature")), None)
    return words.entry(extras["word"]["item"]) | {"in_reading": bool(reading) and words.appears(extras["word"]["item"], reading)}


def render(con, ws_id: str) -> tuple[bytes, bytes]:
    """-> (packet PDF, answer key PDF), built in a temporary folder and returned as bytes."""
    ws = db.worksheet(con, ws_id)
    name = db.student(con, ws["student"])["name"]
    probs = db.problems(con, ws_id)
    extras = db.assignments(con, ws_id)
    word = todays_word(con, ws, extras)
    forecast = json.loads(ws["weather"]) if ws["weather"] else None
    subject = ws["subject"].title() + (" · Placement" if ws["kind"] == "placement" else "")
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        for i in L.MARKERS:
            (build / f"m{i}.svg").write_text(marker_svg(i))
        for icon in ("sun", "partly", "cloud", "fog", "drizzle", "rain", "snow", "storm"):
            (build / f"w-{icon}.svg").write_text(weather_svg(icon))
        pages = number_pages(con, ws, build)
        total = max(pg["page"] + pg.get("pages", 1) - 1 for pg in pages)
        under = {pg["subject"]: pg["lines_top"] for pg in pages if pg.get("lines_top")}
        for n in range(1, total + 1):
            (build / f"qr{n}.svg").write_text(qr_svg(L.qr_payload(ws["id"], n)))
        if "french" in extras and (url := readings.lesson_info(extras["french"]["item"])["url"]):
            (build / "fr.svg").write_text(qr_svg(url, border=1))
        parts = []
        for pg in pages:
            accent = ACCENT.get(pg.get("subject"), ACCENT["math"])
            if pg["kind"] == "reading":
                here = "counter(page).get().first()"
                frame = page_frame(ws, here, total, name, readings.SUBJECTS[pg["subject"]], accent)
                if top := under.get(pg["subject"]):  # the chapter ends high: narrate under it
                    frame += (f"#if {here} == {pg['page'] + pg['pages'] - 1} [\n"
                              f"{narration_page(readings.reading(pg['item']), accent, top, READING_X)}]\n")
                parts.append(reading_section(readings.reading(pg["item"]), accent, "context [\n" + frame + "]"))
                continue
            if pg.get("lines_top"):  # drawn under its chapter, above
                continue
            label_ = "Narration" if pg["kind"] == "narration" else subject
            src = page_frame(ws, pg["page"], total, name, label_, accent)
            top = L.BODY_TOP - 6
            if pg.get("today") and word:
                src += today_panel(word, forecast)
                top = L.FIRST_TOP
            if pg.get("examples"):  # worked examples, with the day's first problems below them
                src += examples_page(con, pg["examples"], top)
            if pg["kind"] == "examples":
                src += examples_page(con, pg["sources"], top)
            elif pg["kind"] == "narration":
                src += narration_page(readings.reading(pg["item"]), accent)
            else:
                src += "".join(problem_slot(p, pg.get("slots", L.LEGACY_SLOTS), pg.get("top", L.BODY_TOP))
                               for p in probs if p["page"] == pg["page"])
            if pg["page"] == 1 and "french" in extras:
                src += french_box(extras["french"]["item"])
            parts.append(f"#page[\n{src}]\n")
        compile_typ(HEADER + "".join(parts), build, build / "packet.pdf")

        rows = "".join(f"[{p['number']}], [{p['prompt']}], [*{esc(p['answer'])}*], "
                       f"[#text(size: 9pt, fill: {col(MUTED)})[{esc(config.skill(p['skill'])['name'])} · L{p['level']} · {p['kind']}]],\n"
                       for p in probs)
        key_src = f"""#set page(paper: "us-letter", margin: 0.6in)
#set text(font: {FONTS}, size: 11.5pt, fill: {col(INK)})
#show math.equation: set text(font: "New Computer Modern Math")
#show heading: set text(weight: 800)
#text(size: 8.5pt, weight: 800, tracking: 0.8pt, fill: {col(ACCENT['math'])})[ANSWER KEY · {esc(subject.upper())}]
#v(-4pt)
#text(size: 20pt, weight: 800)[{esc(name)}] #h(6pt) #text(fill: {col(MUTED)})[{pretty_date(ws['date'])}]
#v(4pt)
#table(columns: (auto, 1fr, auto, auto), inset: 7pt, stroke: (x, y) => (bottom: 0.5pt + {col(HAIR)}),
  table.header([*\\#*], [*Problem*], [*Answer*], [*Skill*]),
{rows})
{also_today(extras, word, forecast)}
#v(1fr)
#text(size: 8pt, fill: {col(MUTED)})[{ws['id']}]"""
        compile_typ(key_src, build, build / "key.pdf")
        return (build / "packet.pdf").read_bytes(), (build / "key.pdf").read_bytes()
