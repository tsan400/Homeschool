"""Build content/ao/year4/ from Project Gutenberg texts, following AmblesideOnline's Year 4 schedule.

    curl -L -o 3761.txt  https://www.gutenberg.org/cache/epub/3761/pg3761.txt    # This Country of Ours
    curl -L -o 56795.txt https://www.gutenberg.org/cache/epub/56795/pg56795.txt  # Fabre's Story-Book of Science
    curl -L -o 1697.txt  https://www.gutenberg.org/cache/epub/1697/pg1697.txt    # Madam How and Lady Why
    uv run python scripts/build_ao.py <folder with those files>

All three books are in the public domain. The week-by-week assignments are AmblesideOnline's
(https://www.amblesideonline.org/year-4-schedule); only chapter numbers and Kingsley's own words
marking where each Madam How reading starts and stops are kept here.
"""

import re
import sys
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parents[1] / "content" / "ao" / "year4"

# This Country of Ours: one chapter a week, weeks 1-36 except the exam week (13).
TCOO = {w: 28 + w - (w > 13) for w in range(1, 37) if w != 13}

# Fabre: two chapters a week. Week 16 has 36 and 37 together; week 8 skips 15-17 and 19, week 31 skips 67-69.
FABRE = {1: [[1], [2]], 2: [[3], [4]], 3: [[5], [6]], 4: [[7], [8]], 5: [[9], [10]], 6: [[11], [12]],
         7: [[13], [14]], 8: [[18], [20]], 9: [[21], [22]], 10: [[23], [24]], 11: [[25], [26]],
         12: [[27], [28]], 13: [[29], [30]], 14: [[31], [32]], 15: [[33], [34]], 16: [[35], [36, 37]],
         17: [[38], [39]], 18: [[40], [41]], 19: [[42], [43]], 20: [[44], [45]], 21: [[46], [47]],
         22: [[48], [49]], 23: [[50], [51]], 24: [[52], [53]], 25: [[54], [55]], 26: [[56], [57]],
         27: [[58], [59]], 28: [[60], [61]], 29: [[62], [63]], 30: [[64], [65]], 31: [[66], [70]],
         32: [[71], [72]], 33: [[73], [74]], 34: [[75], [76]], 35: [[77], [78]], 36: [[79], [80]]}

# Madam How and Lady Why: (chapter, from, to). None = start or end of the chapter.
MADAM_HOW = {
    1: ("PREFACE", None, None),
    2: ("I", None, "than if I had given you a thousand pounds."),
    3: ("I", "But now that we know that How and Why", "I leave you to guess."),
    4: ("I", "So now that I have taught you not", "as a spade above ground."),
    5: ("I", "Now come to the edge of the glen", "I will show you that it was true."),
    6: ("I", "But what could change a beautiful chine", "in plain words, moving ice."),
    7: ("I", "About that moving ice, which", "they are and were created."),
    8: ("II", None, "I myself once felt in the Pyrenees."),
    9: ("II", "I was travelling in the Pyrenees;", "mercies that we are not consumed."),
    10: ("II", "You saw those pictures of the ruins of Arica", "beach, and on to the land."),
    11: ("II", "But there is another way of accounting", "of them which I have given you here."),
    12: ("II", "But you do not seem satisfied yet?", "do you and I, and all mankind, depend."),
    13: ("III", None, "passed him with the Gorgon's head."),
    14: ("III", "But you will see, too, that most of these red", "made, or an old one re-opened."),
    15: ("III", "Now we can understand why earthquakes", "and streams of lava from its sides."),
    16: ("III", "And now, I suppose, you will want to know", "but how that can be, we know not."),
    17: ("III", "Why is a volcano like a cone?", "get a trowel and try this experiment."),
    18: ("III", "Now you ought to understand what", "artillery underneath our feet."),
    19: ("IV", None, "seas which are now firm dry land."),
    20: ("IV", "This is very strange.", "not time to tell about everything."),
    21: ("IV", "And now you will ask me", "world could get on at all."),
    22: ("IV", "Of course, when the lava first cools", "before the worlds were made."),
    23: ("IV", "But now I see you want to ask", "soil fit to feed a great people."),
    24: ("IV", "And now think what a wonderful", "even as seems good to Him."),
    25: ("V", None, "that land is to be fit to live in."),
    26: ("V", "Now you must not ask me to tell", "ground on which we live."),
    27: ("V", "Do I mean that there were ever", "ice-plough are among them."),
    28: ("V", "Or again, if you ever go up Deeside", "we will talk of it next time."),
    29: ("VI", None, "first chapter of my fairy tale."),
    30: ("VI", "Now while all this was going on,", "marvels you ever read in fairy tales."),
    31: ("VI", "You may find the flint weapons", "facts? Who, but God?"),
    32: ("VI", "Then truth is as much larger", "but this is the fairyland of God."),
    33: ("IX", "Then do you think me silly", "whole world wiser than John."),
}
MH_TITLES = {"PREFACE": "Preface", "I": "The Glen", "II": "Earthquakes", "III": "Volcanoes",
             "IV": "The Transformations of a Grain of Soil", "V": "The Ice-Plough",
             "VI": "The True Fairy Tale", "IX": "On Wisdom and Foolishness (from The Coral-Reef)"}

ROMAN = dict(I=1, V=5, X=10, L=50, C=100)


def roman(s: str) -> int:
    n = [ROMAN[c] for c in s]
    return sum(-v if i + 1 < len(n) and v < n[i + 1] else v for i, v in enumerate(n))


SMALL = {"a", "an", "and", "the", "of", "to", "in", "on", "with", "for", "at", "by"}


def title_case(s: str) -> str:
    words = re.sub(r"[’']S\b", "'s", s.title()).split()
    return " ".join(w.lower() if i and w.lower() in SMALL else w for i, w in enumerate(words))


def body(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    start = text.index("\n", text.index("*** START OF")) + 1
    return text[start:text.index("*** END OF")]


def paragraphs(raw: str) -> list[str]:
    """Unwrap Gutenberg's hard-wrapped lines. Indented lines (verse, letters) keep their breaks."""
    out = []
    for block in re.split(r"\n\s*\n", raw.strip("\n")):
        lines = [ln for ln in block.split("\n") if not ln.strip().startswith("[Illustration")]
        if not any(ln.strip() for ln in lines) or set("".join(lines).strip()) <= set("_*- "):
            continue
        if all(ln.startswith("  ") for ln in lines if ln.strip()) and len(lines) > 1:
            out.append("\n".join("> " + ln.strip() for ln in lines if ln.strip()))
        else:
            text = ""
            for ln in (ln.strip() for ln in lines if ln.strip()):
                # A line ending in a hyphen or dash runs straight on: "key-" + "holes", "away--" + "and"
                text += ln if not text or text.endswith("-") else " " + ln
            out.append(text)
    out = [re.sub(r"(?<!-)--(?!-)", "—", re.sub(r"_([^_]+)_", r"\1", p)) for p in out]
    if out:  # Fabre opens each chapter with a capitalised word: "ONE evening" -> "One evening"
        out[0] = re.sub(r"^([A-Z])([A-Z]+)\b", lambda m: m[1] + m[2].lower(), out[0])
    return out


def flat(s: str) -> str:
    """Letters and digits only, so punctuation and spacing differences between editions don't matter."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def tcoo(src: Path) -> dict[int, tuple[str, str]]:
    text = body(src)
    heads = list(re.finditer(r"^Chapter (\d+) - (.+)$", text, re.M))
    return {int(m[1]): (m[2].strip(), text[m.end():heads[i + 1].start() if i + 1 < len(heads) else None])
            for i, m in enumerate(heads)}


def fabre(src: Path) -> dict[int, tuple[str, str]]:
    text = body(src)
    heads = list(re.finditer(r"^ +CHAPTER ([IVXLC]+)\s*\n\s*\n +(.+)$", text, re.M))
    chapters = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else text.find("INDEX", m.end())
        chapters[roman(m[1])] = (title_case(m[2].strip()), text[m.end():end])
    return chapters


def madam_how(src: Path) -> dict[str, str]:
    text = body(src)
    heads = list(re.finditer(r"^(PREFACE|CHAPTER ([IVX]+)--.+)$", text, re.M))
    return {(m[2] or "PREFACE"): text[m.end():heads[i + 1].start() if i + 1 < len(heads) else None]
            for i, m in enumerate(heads)}


def cut(chapter: str, start: str | None, stop: str | None, until: str | None = None) -> str:
    """The part of a chapter from the paragraph containing `start` to the end of `stop`, or to just
    before `until` (the next reading's start, which is more reliable: editions word endings differently)."""
    paras = paragraphs(chapter)
    joined = "".join(paras)
    i = 0
    if start:
        i = flat(joined).find(flat(start))
        if i < 0:
            raise ValueError(f"start not found: {start!r}")
    j = len(flat(joined))
    if until:
        j = flat(joined).find(flat(until), i + 1)
        if j < 0:
            raise ValueError(f"next start not found: {until!r}")
    elif stop:
        j = flat(joined).find(flat(stop), i)
        if j < 0:  # last reading of the chapter, worded differently in this edition
            print(f"  note: {stop!r} not found; reading to the end of the chapter")
            j = len(flat(joined))
        else:
            j += len(flat(stop))
    # Map back to whole paragraphs: keep every paragraph overlapping [i, j).
    keep, pos = [], 0
    for p in paras:
        n = len(flat(p))
        if pos + n > i and pos < j:
            keep.append(p)
        pos += n
    return "\n\n".join(keep)


def main(folder: str):
    src = Path(folder)
    t, f, mh = tcoo(src / "3761.txt"), fabre(src / "56795.txt"), madam_how(src / "1697.txt")
    readings = []

    def add(rid, stream, week, book, title, text):
        (OUT / "text" / f"{rid}.txt").write_text(text + "\n")
        readings.append(dict(id=rid, stream=stream, week=week, book=book, title=title,
                             words=len(text.split())))

    (OUT / "text").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "text").glob("*.txt"):
        old.unlink()
    for week in range(1, 37):
        if week in TCOO:
            n = TCOO[week]
            title, raw = t[n]
            add(f"tcoo-{n}", "history", week, "This Country of Ours", f"Chapter {n}: {title}", "\n\n".join(paragraphs(raw)))
        for chs in FABRE[week]:
            title = " / ".join(f[c][0] for c in chs)
            text = "\n\n".join(("\n\n" if k else "") + (f"## {f[c][0]}\n\n" if len(chs) > 1 else "") +
                               "\n\n".join(paragraphs(f[c][1])) for k, c in enumerate(chs))
            label = "Chapters " + " and ".join(map(str, chs)) if len(chs) > 1 else f"Chapter {chs[0]}"
            add(f"fabre-{'-'.join(map(str, chs))}", "science", week, "The Story-Book of Science", f"{label}: {title}", text.strip())
        if week in MADAM_HOW:
            ch, a, b = MADAM_HOW[week]
            part = f"week {week}" if a or b else "whole"
            title = MH_TITLES[ch] if ch == "PREFACE" else f"Chapter {roman(ch)}: {MH_TITLES[ch]}"
            if a or b:
                same = [w for w, v in MADAM_HOW.items() if v[0] == ch]
                if len(same) > 1:
                    title += f" (part {same.index(week) + 1} of {len(same)})"
            nxt = MADAM_HOW.get(week + 1)
            until = nxt[1] if nxt and nxt[0] == ch else None
            add(f"madamhow-{week}", "nature", week, "Madam How and Lady Why", title, cut(mh[ch], a, b, until))
    meta = {"year": 4,
            "source": "AmblesideOnline Year 4 schedule, https://www.amblesideonline.org/year-4-schedule",
            "books": {"This Country of Ours": "H. E. Marshall, 1917 (Project Gutenberg #3761)",
                      "The Story-Book of Science": "Jean-Henri Fabre, tr. F. C. Bicknell, 1917 (Project Gutenberg #56795)",
                      "Madam How and Lady Why": "Charles Kingsley, 1869 (Project Gutenberg #1697)"},
            "readings": readings}
    (OUT / "readings.yaml").write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=120))
    for s in ("history", "science", "nature"):
        r = [x for x in readings if x["stream"] == s]
        print(f"{s}: {len(r)} readings, {min(x['words'] for x in r)}-{max(x['words'] for x in r)} words")


if __name__ == "__main__":
    main(sys.argv[1])
