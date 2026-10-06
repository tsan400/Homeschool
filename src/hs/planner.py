"""Chooses each day's problems and stores the worksheet. Rendering happens separately."""

import json

from hs import config, db, layout as L, readings, weather, words
from hs.generators.math import generate

EXAMPLES_PER_PAGE = 3
EXAMPLES_FIRST_PAGE = 2   # page 1 shares its space with the weather and the word of the day


def plan_daily(con, student: str) -> tuple[list[dict], list[int]]:
    """Returns (problem specs, ids of stuck problems to show as worked examples)."""
    s = config.settings()["math"]
    levels = db.levels(con, student)
    order = [sk["id"] for sk in config.skills()]
    total = s["problems_per_day"]

    # Stuck problems from earlier packets -> worked example + two scaffolded variants.
    stuck = con.execute("""SELECT p.* FROM response r JOIN problem p ON p.id = r.problem_id
        JOIN worksheet w ON w.id = p.worksheet_id
        WHERE w.student=? AND w.kind != 'test' AND r.stuck=1 AND r.scaffolded=0 AND r.excluded=0
        ORDER BY w.date DESC, p.number LIMIT ?""", (student, s["max_stuck_examples"])).fetchall()
    scaffolds = []
    for p in stuck:
        scaffolds += [dict(skill=p["skill"], level=max(1, p["level"] - 1), kind="scaffold", source=p["id"]),
                      dict(skill=p["skill"], level=p["level"], kind="scaffold", source=p["id"])]

    # Spaced review: mastered skills, least recently seen first.
    mastered = sorted((r for r in levels.values() if r["mastered"]),
                      key=lambda r: (r["last_seen"] or "", order.index(r["skill"])))
    n_review = round(total * s["review_fraction"]) if mastered else 0
    review = [dict(skill=mastered[i % len(mastered)]["skill"], level=mastered[i % len(mastered)]["level"], kind="review")
              for i in range(n_review)]

    # New work at the edge: the first few unmastered skills, at their current level.
    remaining = total - len(scaffolds) - len(review)
    active = [sid for sid in order if sid in levels and not levels[sid]["mastered"]][: s["active_skills"]]
    new = []
    if active and remaining > 0:
        use = active[: max(1, min(len(active), remaining // s["min_per_skill"]))]
        for i in range(remaining):
            sid = use[i * len(use) // remaining]
            new.append(dict(skill=sid, level=levels[sid]["level"], kind="new"))
    return review + scaffolds + new, [p["id"] for p in stuck]


def plan_placement(con, student: str) -> list[dict]:
    g = db.student(con, student)["math_grade"]
    return [dict(skill=sk["id"], level=lvl, kind="placement")
            for sk in config.skills() if g - 1 <= sk["grade"] <= g + 1 for lvl in (2, 4)]


def plan_test() -> list[dict]:
    """A short calibration packet: one problem from each of 10 skills, any level."""
    sks = config.skills()
    return [dict(skill=sks[i * len(sks) // 10]["id"], level=3, kind="new") for i in range(10)]


def positions(n: int, per: int, first: int) -> list[tuple[int, int]]:
    """(page offset, slot) for n problems, `per` to a page, the first page starting at slot `first`."""
    out, page, slot = [], 0, first
    for _ in range(n):
        if slot > per:
            page, slot = page + 1, 1
        out.append((page, slot))
        slot += 1
    return out


def create(con, student: str, date: str, kind: str = "daily") -> str:
    ws_id = f"{date}-{student}-math" + ("" if kind == "daily" else f"-{kind}")
    st = db.student(con, student)
    if kind == "daily":
        specs, sources = plan_daily(con, student)
    else:
        specs, sources = (plan_placement(con, student) if kind == "placement" else plan_test()), []

    groups = [sources[:EXAMPLES_FIRST_PAGE]] + [sources[j:j + EXAMPLES_PER_PAGE]
                                                for j in range(EXAMPLES_FIRST_PAGE, len(sources), EXAMPLES_PER_PAGE)]
    pages = [{"page": i + 1, "kind": "examples", "sources": g} for i, g in enumerate(groups) if g]
    first_problem_page = len(pages) + 1
    per = config.settings()["math"]["problems_per_page"]
    # Page 1 opens with the weather and the word of the day, so its problems start lower down.
    where = positions(len(specs), per, 1 + L.today_slots(per) if first_problem_page == 1 else 1)
    n_pages = where[-1][0] + 1 if where else 0
    pages += [{"page": first_problem_page + i, "kind": "problems", "slots": per} for i in range(n_pages)]
    if pages:
        pages[0]["today"] = True

    extras = readings.plan(con, st, date) if kind == "daily" else []
    reading = next((readings.text(x["item"]) for x in extras if x["subject"] != "french"), None)
    word = words.pick(con, st, date, reading)
    forecast = weather.for_family(db.family(con, st["family_id"]), date)
    con.execute("INSERT INTO worksheet (id, student, date, subject, kind, status, pages, weather) VALUES (?,?,?,?,?,?,?,?)",
                (ws_id, student, date, "math", kind, "printed", json.dumps(pages), json.dumps(forecast) if forecast else None))
    seen = set()
    for i, spec in enumerate(specs):
        for attempt in range(20):  # avoid repeating a problem within one packet
            seed = f"{ws_id}:{i}:{attempt}"
            prob = generate(spec["skill"], spec["level"], seed)
            if prob.prompt not in seen:
                break
        seen.add(prob.prompt)
        con.execute("""INSERT INTO problem (worksheet_id, page, slot, number, skill, level, kind, seed,
                       prompt, answer, form, hint, steps, source_problem_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ws_id, first_problem_page + where[i][0], where[i][1], i + 1, spec["skill"], spec["level"],
                     spec["kind"], seed, prob.prompt, prob.answer, prob.form, prob.hint, json.dumps(prob.steps),
                     spec.get("source")))
    con.execute("INSERT INTO assignment (worksheet_id, subject, item, page) VALUES (?,?,?,1)", (ws_id, "word", word["word"]))
    if extras:
        for extra in extras:
            page = 1
            if extra["subject"] != "french":  # numbered for real when the packet is rendered
                page = len(pages) + 2
                pages += [{"page": page - 1, "kind": "reading", **extra}, {"page": page, "kind": "narration", **extra}]
            con.execute("INSERT INTO assignment (worksheet_id, subject, item, page) VALUES (?,?,?,?)",
                        (ws_id, extra["subject"], extra["item"], page))
        con.execute("UPDATE worksheet SET pages=? WHERE id=?", (json.dumps(pages), ws_id))
    con.executemany("UPDATE response SET scaffolded=1 WHERE problem_id=?", [(pid,) for pid in sources])
    con.commit()
    return ws_id
