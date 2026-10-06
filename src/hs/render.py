"""Builds packet and answer-key PDFs with Typst. All placement uses layout.py coordinates.

Look: quiet and friendly, in black and white. Nunito for words, Fira Math for numbers, Literata for
readings; light gray only for small labels, number badges and rules. Anything the scanner reads
(answer boxes, circles, writing lines) stays plain dark-on-white at the coordinates in layout.py.
"""

import json
import re
import tempfile
from datetime import date as Date
from pathlib import Path

import cv2
import pypdfium2 as pdfium
import segno
import typst

from hs import config, db, layout as L, readings, words

FONT_DIR = Path(__file__).parent / "fonts"
FONTS = '("Nunito", "DejaVu Sans")'
INK, MUTED, HAIR, LINE = "#1a1a1a", "#6b6b6b", "#d4d4d4", "#333333"
# One accent per subject. Black and white for now; a colour here shows up in that subject's
# labels, badges and rules.
ACCENT = dict.fromkeys(("math", "history", "science", "nature", "french", "word"), INK)
HEADER = f"""#set page(width: {L.PAGE_W}pt, height: {L.PAGE_H}pt, margin: 0pt)
#set text(font: {FONTS}, size: 16pt, fill: rgb("{INK}"))
#show math.equation: set text(font: ("Fira Math", "New Computer Modern Math"))
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


def qr_svg(payload: str, border: int = 2) -> str:
    """The page's QR code with soft, rounded shapes. The scanner only needs the corner squares'
    1:1:3:1:1 stripes and each module's centre, and rounding keeps both."""
    matrix = segno.make(payload, error="m").matrix
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


# ---------- weather icons: simple line drawings with a little colour ----------

_CLOUD = "M13 36 H36 A7 7 0 0 0 36 22 A10 10 0 0 0 17 19 A8 8 0 0 0 13 36 Z"
_STROKE = f'stroke="{INK}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"'


RAYS = ((1, 0), (.707, .707), (0, 1), (-.707, .707), (-1, 0), (-.707, -.707), (0, -1), (.707, -.707))


def _sun(cx, cy, r, rays=RAYS):
    rays = "".join(f'<line x1="{cx + (r + 4) * c:.1f}" y1="{cy + (r + 4) * s:.1f}" x2="{cx + (r + 8) * c:.1f}" '
                   f'y2="{cy + (r + 8) * s:.1f}"/>' for c, s in rays)
    return f'<g {_STROKE}><circle cx="{cx}" cy="{cy}" r="{r}" fill="#ffffff"/>{rays}</g>'


def _cloud(transform=""):
    return f'<path d="{_CLOUD}" fill="#ffffff" {_STROKE} transform="{transform}"/>'


def _below(kind):
    xs = (16, 24, 32)
    if kind == "rain":
        return "".join(f'<line x1="{x}" y1="35" x2="{x - 3}" y2="43" stroke="{INK}" stroke-width="2" stroke-linecap="round"/>' for x in xs)
    if kind == "drizzle":
        return "".join(f'<circle cx="{x - 1}" cy="{38 + (x == 24) * 4}" r="1.6" fill="{INK}"/>' for x in xs)
    if kind == "snow":
        return "".join(f'<g stroke="{INK}" stroke-width="1.4" stroke-linecap="round" transform="translate({x - 1} {39 + (x == 24) * 4})">'
                       '<line x1="-3" y1="0" x2="3" y2="0"/><line x1="-1.5" y1="-2.6" x2="1.5" y2="2.6"/>'
                       '<line x1="-1.5" y1="2.6" x2="1.5" y2="-2.6"/></g>' for x in xs)
    if kind == "storm":
        return f'<polygon points="26,30 19,40 24,40 21,47 31,35 26,35 29,30" fill="{INK}" {_STROKE}/>'
    if kind == "fog":
        return (f'<g stroke="{MUTED}" stroke-width="2" stroke-linecap="round"><line x1="9" y1="37" x2="39" y2="37"/>'
                '<line x1="13" y1="43" x2="35" y2="43"/></g>')
    return ""


def weather_svg(icon: str) -> str:
    if icon == "sun":
        body = _sun(24, 24, 9)
    elif icon == "partly":
        body = _sun(17, 17, 6.5, RAYS[3:]) + _cloud("translate(5 6) scale(0.86)")  # rays only where the cloud isn't
    elif icon == "cloud":
        body = _cloud()
    else:
        body = _cloud("translate(0 -7)") + _below(icon)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">{body}</svg>'


# ---------- pieces of a page ----------

def pretty_date(iso: str) -> str:
    d = Date.fromisoformat(iso)
    return d.strftime("%A, %B ") + str(d.day) + d.strftime(", %Y")


def chip(label: str, accent: str) -> str:
    return (f"#box(fill: {tint(accent)}, inset: (x: 7pt, y: 4pt), radius: 8pt, baseline: 3pt)"
            f"[#text(size: 8.5pt, weight: 800, tracking: 0.7pt, fill: {col(accent)})[{esc(label.upper())}]]")


def page_frame(ws, page, total: int, student_name: str, label: str, accent: str) -> str:
    """Markers, QR code, header and page number on every page. `page` is a number, or Typst code
    for one (reading pages flow, so their number is only known while Typst lays them out)."""
    out = "".join(at(x, y, f'#image("m{i}.svg", width: {L.MARKER}pt)') for i, (x, y) in L.MARKERS.items())
    qr = f'"qr{page}.svg"' if isinstance(page, int) else f'"qr" + str({page}) + ".svg"'
    out += at(L.QR[0], L.QR[1], f"#image({qr}, width: {L.QR[2]}pt)")
    out += at(76, 24, f"#text(size: 22pt, weight: 800)[{esc(student_name)}] #h(5pt) {chip(label, accent)}")
    out += at(76, 57, f"#text(size: 11pt, fill: {col(MUTED)})[{pretty_date(ws['date'])}]")
    number = page if isinstance(page, int) else f"#{page}"
    out += at(0, 745, f"#box(width: 540pt)[#align(right)[#text(size: 9pt, fill: {col(MUTED)})[Page {number} of {total}]]]")
    return out


def label(text: str) -> str:
    return f"#text(size: 8pt, weight: 800, tracking: 1pt, fill: {col(MUTED)})[{esc(text)}]"


def word_card(word: dict) -> str:
    accent = ACCENT["word"]
    parts = [label("WORD OF THE DAY"),
             f"[#text(size: 26pt, weight: 800, fill: {col(accent)})[{esc(word['word'])}] #h(4pt) "
             f"#text(size: 11pt, style: \"italic\", fill: {col(MUTED)})[{esc(word['pos'])}]]",
             f"[#text(size: 12pt)[{esc(word['meaning'])}]]",
             f"block(stroke: (left: 2pt + {tint(accent, 70)}), inset: (left: 9pt, y: 2pt))"
             f"[#text(font: \"Literata\", size: 11.5pt, style: \"italic\")[“{esc(word['sentence'])}”]]"]
    if word.get("in_reading"):
        parts.append(f"[#text(size: 9pt, fill: {col(MUTED)})[Look for it in today's reading.]]")
    return "#stack(spacing: 8pt, " + ", ".join(p if not p.startswith("#") else f"[{p}]" for p in parts) + ")"


def weather_card(w: dict) -> str:
    temps = (f"#text(fill: {col(MUTED)})[High] *{w['high']}°* #h(6pt) #text(fill: {col(MUTED)})[Low] *{w['low']}°*")
    notes = ", ".join(f"[{esc(n)}]" for n in w["notes"])
    town = esc(w.get("place", "").split(",")[0])
    foot = " · ".join(x for x in (town, f"sunrise {w['sunrise']}", f"sunset {w['sunset']}") if x)
    return (f"#stack(spacing: 9pt, [{label('WEATHER')}], "
            f"grid(columns: (46pt, 1fr), column-gutter: 10pt, align: horizon, image(\"w-{w['icon']}.svg\", width: 46pt), "
            f"stack(spacing: 6pt, [#text(size: 15pt, weight: 800)[{esc(w['sky'])}]], [#text(size: 12pt)[{temps}]])), "
            f"[#set text(size: 10pt)\n#stack(spacing: 5pt, {notes})])\n"
            f"#place(bottom + left)[#text(size: 8pt, fill: {col(MUTED)})[{foot}]]")


def today_panel(word: dict, forecast: dict | None) -> str:
    """Page 1's opening: the weather and the word of the day."""
    y, h = L.BODY_TOP + 6, L.TODAY_H - 12

    def card(x, w, body):
        return at(x, y, f"#block(width: {w}pt, height: {h}pt, stroke: 0.75pt + {col(HAIR)}, radius: 12pt, "
                        f"inset: (x: 16pt, y: 14pt))[{body}]")
    if forecast:
        return card(40, 204, weather_card(forecast)) + card(256, 316, word_card(word))
    return card(40, 532, word_card(word))


def number_badge(n: int, accent: str) -> str:
    return (f"#box(width: 22pt, height: 22pt, radius: 11pt, fill: {tint(accent)})"
            f"[#align(center + horizon)[#text(size: 11pt, weight: 800, fill: {col(accent)})[{n}]]]")


def problem_slot(p, slots: int) -> str:
    top = L.slot_top(p["slot"], slots)
    x, y, w, h = L.answer_box(p["slot"], slots)
    out = at(40, top, f"#line(length: {L.PAGE_W - 80}pt, stroke: 0.6pt + {col(HAIR)})")
    out += at(34, top + 15, number_badge(p["number"], ACCENT["math"]))
    out += at(66, top + 16, f'#block(width: 300pt)[#set text(size: 18pt)\n{big(p["prompt"])}]')
    out += at(x + 2, y - 12, f"#text(size: 8pt, fill: {col(MUTED)})[Answer]")
    out += at(x, y, f"#rect(width: {w}pt, height: {h}pt, stroke: 1.1pt + {col(LINE)}, radius: 7pt)")
    for which, text in (("stuck", "stuck"), ("easy", "too easy")):
        cx, cy, r = L.bubble(p["slot"], which, slots)
        out += at(cx - r, cy - r, f"#circle(radius: {r}pt, stroke: 1pt + {col(LINE)})")
        out += at(cx + r + 4, cy - 6, f"#text(size: 9pt, fill: {col(MUTED)})[{text}]")
    return out


def examples_page(con, ids: list[int], top: float) -> str:
    body = [f"[#text(size: 17pt, weight: 800, fill: {col(ACCENT['math'])})[Let's look again]]",
            f"[#text(size: 10.5pt, fill: {col(MUTED)})[You marked these as stuck. Read each example, then try the practice problems in this packet.]]"]
    for pid in ids:
        p = con.execute("SELECT p.*, w.date FROM problem p JOIN worksheet w ON w.id = p.worksheet_id WHERE p.id=?", (pid,)).fetchone()
        steps = "\n".join(f"+ {big(s)}" for s in db.steps(p))
        body.append(f"[#line(length: 100%, stroke: 0.6pt + {col(HAIR)})\n#set text(size: 13pt)\n"
                    f"*Problem {p['number']} from {pretty_date(p['date'])}:* {big(p['prompt'])}\n\n{steps}\n\n"
                    f"*Answer:* {esc(p['answer'])}]")
    return at(56, top, f"#block(width: {L.PAGE_W - 112}pt)[#stack(spacing: 10pt, {', '.join(body)})]")


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
    return (f"#page(margin: (top: 104pt, bottom: 82pt, x: 70pt), background: {frame or 'none'})[\n"
            "#set text(font: \"Literata\", size: 12.5pt)\n"
            "#set par(justify: true, leading: 0.68em, spacing: 0.75em, first-line-indent: 1.2em)\n"
            + reading_body(r, accent) + "\n]\n")


def narration_page(r: dict, accent: str) -> str:
    title = r["title"].partition(": ")[2] or r["title"]
    out = at(56, 102, f"#block(width: {L.PAGE_W - 112}pt)[#stack(spacing: 8pt, "
                      f"[#text(size: 17pt, weight: 800)[Tell it back]], "
                      f"[#text(size: 12pt)[#text(weight: 700, fill: {col(accent)})[{esc(r['book'])}] · {esc(title)}]], "
                      f"[#text(size: 10pt, fill: {col(MUTED)})[Tell what you read in your own words. Say it out loud to a parent, "
                      f"or write it on the lines: who, where, what happened first and next. You may draw a picture too.]])]")
    y = L.NARRATION_TOP
    while y < L.BODY_BOTTOM:
        out += at(56, y, f"#line(length: {L.PAGE_W - 112}pt, stroke: 0.6pt + rgb(\"#a3abb4\"))")
        y += L.LINE_GAP
    return out


def french_box(item: str) -> str:
    cx, cy, r = L.FRENCH
    return (at(cx - r, cy - r, f"#circle(radius: {r}pt, stroke: 1pt + {col(LINE)})")
            + at(cx + r + 7, cy - 6, f"#text(size: 10pt)[#text(weight: 800, fill: {col(ACCENT['french'])})[French] #h(3pt) "
                                     f"{esc(readings.french_label(item))} #text(fill: {col(MUTED)})[· fill in the circle when you're done]]"))


def also_today(extras, word: dict | None, forecast: dict | None) -> str:
    """Parent's notes for the key: the word, the reading and the French lesson."""
    lines = []
    if word:
        lines.append(f"- *Word of the day:* {esc(word['word'])} ({esc(word['pos'])}): {esc(word['meaning'])} "
                     f"Ask them to use it in a sentence of their own today.")
    for subject, a in extras.items():
        if subject == "french":
            lines.append(f"- *French:* {esc(readings.french_label(a['item']))}. Listen and repeat out loud; no reading or spelling yet.")
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
    its own) and give every page its final number. Math pages come first and keep theirs."""
    pages = [pg for pg in json.loads(ws["pages"]) if pg["kind"] in ("examples", "problems")]
    for pg in json.loads(ws["pages"]):
        if pg["kind"] == "reading":
            compile_typ(HEADER + reading_section(readings.reading(pg["item"]), ACCENT[pg["subject"]]), build, build / "count.pdf")
            n = len(pdfium.PdfDocument((build / "count.pdf").read_bytes()))
            pages.append(pg | {"page": len(pages) + 1, "pages": n})
        elif pg["kind"] == "narration":
            page = pages[-1]["page"] + pages[-1]["pages"]
            pages.append(pg | {"page": page})
            con.execute("UPDATE assignment SET page=? WHERE worksheet_id=? AND subject=?", (page, ws["id"], pg["subject"]))
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
        total = pages[-1]["page"] + pages[-1].get("pages", 1) - 1
        for n in range(1, total + 1):
            (build / f"qr{n}.svg").write_text(qr_svg(L.qr_payload(ws["id"], n)))
        parts = []
        for pg in pages:
            accent = ACCENT.get(pg.get("subject"), ACCENT["math"])
            if pg["kind"] == "reading":
                frame = "context [\n" + page_frame(ws, "counter(page).get().first()", total, name,
                                                   readings.SUBJECTS[pg["subject"]], accent) + "]"
                parts.append(reading_section(readings.reading(pg["item"]), accent, frame))
                continue
            label_ = "Narration" if pg["kind"] == "narration" else subject
            src = page_frame(ws, pg["page"], total, name, label_, accent)
            top = L.BODY_TOP - 6
            if pg.get("today") and word:
                src += today_panel(word, forecast)
                top = L.BODY_TOP + L.TODAY_H + 4
            if pg["kind"] == "examples":
                src += examples_page(con, pg["sources"], top)
            elif pg["kind"] == "narration":
                src += narration_page(readings.reading(pg["item"]), accent)
            else:
                src += "".join(problem_slot(p, pg.get("slots", L.LEGACY_SLOTS)) for p in probs if p["page"] == pg["page"])
            if pg["page"] == 1 and "french" in extras:
                src += french_box(extras["french"]["item"])
            parts.append(f"#page[\n{src}]\n")
        compile_typ(HEADER + "".join(parts), build, build / "packet.pdf")

        rows = "".join(f"[{p['number']}], [{p['prompt']}], [*{esc(p['answer'])}*], "
                       f"[#text(size: 9pt, fill: {col(MUTED)})[{esc(config.skill(p['skill'])['name'])} · L{p['level']} · {p['kind']}]],\n"
                       for p in probs)
        key_src = f"""#set page(paper: "us-letter", margin: 0.6in)
#set text(font: {FONTS}, size: 11.5pt, fill: {col(INK)})
#show math.equation: set text(font: ("Fira Math", "New Computer Modern Math"))
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
