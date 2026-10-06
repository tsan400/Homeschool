"""Builds packet and answer-key PDFs with Typst. All placement uses layout.py coordinates."""

import json
import re
import tempfile
from datetime import date as Date
from pathlib import Path

import cv2
import segno
import typst

from hs import config, db, layout as L

FONTS = '("DejaVu Sans", "Helvetica", "Arial", "Libertinus Serif")'
HEADER = f"""#set page(width: {L.PAGE_W}pt, height: {L.PAGE_H}pt, margin: 0pt)
#set text(font: {FONTS}, size: 16pt)
"""


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


def pretty_date(iso: str) -> str:
    d = Date.fromisoformat(iso)
    return d.strftime("%A, %B ") + str(d.day) + d.strftime(", %Y")


def page_frame(build: Path, ws, page: int, total: int, student_name: str) -> str:
    """Markers, QR code, and header shared by every page."""
    qr = build / f"qr{page}.svg"
    segno.make(L.qr_payload(ws["id"], page), error="m").save(qr, kind="svg", border=2)
    out = "".join(at(x, y, f'#image("m{i}.svg", width: {L.MARKER}pt)') for i, (x, y) in L.MARKERS.items())
    out += at(L.QR[0], L.QR[1], f'#image("{qr.name}", width: {L.QR[2]}pt)')
    title = f"{esc(student_name)} · {esc(ws['subject'].title())}" + (" · Placement" if ws["kind"] == "placement" else "")
    out += at(76, 26, f"#text(size: 22pt, weight: \"bold\")[{title}]")
    out += at(76, 56, f"#text(size: 12pt)[{pretty_date(ws['date'])} #h(1em) Page {page} of {total}]")
    return out


def problem_slot(p) -> str:
    top = L.slot_top(p["slot"])
    x, y, w, h = L.answer_box(p["slot"])
    out = at(24, top, f"#line(length: {L.PAGE_W - 48}pt, stroke: 0.5pt + gray)")
    out += at(30, top + 16, f'#text(weight: "bold")[{p["number"]}.]')
    out += at(64, top + 16, f'#block(width: 300pt)[#set text(size: 18pt)\n{big(p["prompt"])}]')
    out += at(x, y - 13, "#text(size: 9pt, fill: gray)[Answer]")
    out += at(x, y, f"#rect(width: {w}pt, height: {h}pt, stroke: 1.2pt, radius: 4pt)")
    for which, label in (("stuck", "stuck"), ("easy", "too easy")):
        cx, cy, r = L.bubble(p["slot"], which)
        out += at(cx - r, cy - r, f"#circle(radius: {r}pt, stroke: 1pt)")
        out += at(cx + r + 4, cy - 6, f"#text(size: 10pt)[{label}]")
    return out


def examples_page(con, ids: list[int]) -> str:
    body = ["#set text(size: 14pt)",
            "#text(size: 16pt, weight: \"bold\")[Let's look again] \\",
            "#text(size: 11pt)[You marked these as stuck. Read each example, then try the practice problems in this packet.]",
            "#v(8pt)"]
    for pid in ids:
        p = con.execute("SELECT p.*, w.date FROM problem p JOIN worksheet w ON w.id = p.worksheet_id WHERE p.id=?", (pid,)).fetchone()
        steps = "\n".join(f"+ {big(s)}" for s in db.steps(p))
        body.append(f"#line(length: 100%, stroke: 0.5pt + gray)\n*Problem {p['number']} from {pretty_date(p['date'])}:* {big(p['prompt'])}\n\n"
                    f"{steps}\n\n*Answer:* {esc(p['answer'])}\n#v(6pt)")
    return at(56, 106, f"#block(width: {L.PAGE_W - 112}pt)[\n" + "\n".join(body) + "\n]")


def instructions() -> str:
    return at(76, 76, "#block(width: 380pt)[#text(size: 10pt, fill: rgb(\"#444\"))[Show your work in the space. Write your final answer in the box. "
                      "Fill in a circle if you got *stuck* or if a problem was *too easy*.]]")


def compile_typ(source: str, build: Path, out: Path):
    (build / "main.typ").write_text(source)
    typst.compile(str(build / "main.typ"), output=str(out), root=str(build))


def render(con, ws_id: str) -> tuple[bytes, bytes]:
    """-> (packet PDF, answer key PDF), built in a temporary folder and returned as bytes."""
    ws = db.worksheet(con, ws_id)
    name = db.student(con, ws["student"])["name"]
    pages = json.loads(ws["pages"])
    probs = db.problems(con, ws_id)
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        for i in L.MARKERS:
            (build / f"m{i}.svg").write_text(marker_svg(i))
        parts = []
        for pg in pages:
            src = page_frame(build, ws, pg["page"], len(pages), name)
            if pg["kind"] == "examples":
                src += examples_page(con, pg["sources"])
            else:
                if pg["page"] == next(p["page"] for p in pages if p["kind"] == "problems"):
                    src += instructions()
                src += "".join(problem_slot(p) for p in probs if p["page"] == pg["page"])
            parts.append(src)
        compile_typ(HEADER + "#pagebreak()\n".join(parts), build, build / "packet.pdf")

        rows = "".join(f"[{p['number']}], [{p['prompt']}], [*{esc(p['answer'])}*], "
                       f"[#text(size: 9pt)[{esc(config.skill(p['skill'])['name'])} L{p['level']} {p['kind']}]],\n" for p in probs)
        key_src = f"""#set page(paper: "us-letter", margin: 0.6in)
#set text(font: {FONTS}, size: 12pt)
= Answer key: {esc(name)}, {esc(ws['subject'].title())}
{pretty_date(ws['date'])} #h(1em) #text(fill: gray)[{ws['id']}]
#v(8pt)
#table(columns: (auto, 1fr, auto, auto), inset: 7pt, stroke: 0.5pt + gray,
  [*\\#*], [*Problem*], [*Answer*], [*Skill*],
{rows})
"""
        compile_typ(key_src, build, build / "key.pdf")
        return (build / "packet.pdf").read_bytes(), (build / "key.pdf").read_bytes()
