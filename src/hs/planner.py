"""Chooses each day's problems and stores the worksheet. Rendering happens separately."""

import json

from hs import config, db, layout as L
from hs.generators.math import generate

EXAMPLES_PER_PAGE = 3


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


def create(con, student: str, date: str, kind: str = "daily") -> str:
    ws_id = f"{date}-{student}-math" + ("" if kind == "daily" else f"-{kind}")
    if kind == "daily":
        specs, sources = plan_daily(con, student)
    else:
        specs, sources = (plan_placement(con, student) if kind == "placement" else plan_test()), []

    pages = [{"page": i + 1, "kind": "examples", "sources": sources[j:j + EXAMPLES_PER_PAGE]}
             for i, j in enumerate(range(0, len(sources), EXAMPLES_PER_PAGE))]
    first_problem_page = len(pages) + 1
    per = config.settings()["math"]["problems_per_page"]
    n_pages = -(-len(specs) // per)
    pages += [{"page": first_problem_page + i, "kind": "problems", "slots": per} for i in range(n_pages)]

    con.execute("INSERT INTO worksheet (id, student, date, subject, kind, status, pages) VALUES (?,?,?,?,?,?,?)",
                (ws_id, student, date, "math", kind, "printed", json.dumps(pages)))
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
                    (ws_id, first_problem_page + i // per, i % per + 1, i + 1, spec["skill"], spec["level"],
                     spec["kind"], seed, prob.prompt, prob.answer, prob.form, prob.hint, json.dumps(prob.steps),
                     spec.get("source")))
    con.executemany("UPDATE response SET scaffolded=1 WHERE problem_id=?", [(pid,) for pid in sources])
    con.commit()
    return ws_id
