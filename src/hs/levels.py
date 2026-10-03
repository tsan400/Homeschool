"""Level rules. `update` is pure; `approve` applies a reviewed worksheet to the database."""

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime

from hs import config, db


@dataclass(frozen=True)
class State:
    level: int = 1
    up: int = 0         # consecutive qualifying sessions >= up_pct
    down: int = 0       # consecutive sessions < down_pct
    mastered: bool = False


def update(s: State, n: int, n_correct: int, n_too_easy: int, rules: dict, max_level: int = 5) -> State:
    """Apply one session of a skill. Sessions smaller than min_problems don't count."""
    if n < rules["min_problems"] or s.mastered:
        return s
    pct = n_correct / n
    up = s.up + 1 if pct >= rules["up_pct"] else 0
    down = s.down + 1 if pct < rules["down_pct"] else 0
    fast = pct >= rules["up_pct"] and n_too_easy / n > rules["too_easy_fast_track"]
    if up >= rules["up_sessions"] or fast:
        if s.level >= max_level:
            return State(max_level, 0, 0, True)
        return State(s.level + 1, 0, 0, False)
    if down >= rules["down_sessions"]:
        return State(max(1, s.level - 1), 0, 0, False)
    return replace(s, up=up, down=down)


def seed(con, student: dict):
    """Create level rows for any skills a student doesn't have yet. Never resets existing rows."""
    for sk in config.skills():
        mastered = sk["grade"] < student["math_grade"]
        con.execute("INSERT OR IGNORE INTO skill_level (student, skill, level, mastered) VALUES (?,?,?,?)",
                    (student["id"], sk["id"], len(sk["levels"]) if mastered else 1, int(mastered)))
    con.commit()


def placement_result(n_correct: int, max_level: int = 5) -> State:
    """Two placement problems (levels 2 and 4): both right -> mastered, one -> level 3, none -> level 1."""
    return {2: State(max_level, mastered=True), 1: State(3)}.get(n_correct, State(1))


def approve(con, ws_id: str) -> list[str]:
    """Turn a reviewed worksheet into sessions and level changes. Returns human-readable changes."""
    ws = db.worksheet(con, ws_id)
    if ws["kind"] == "test":  # calibration packets never touch levels
        con.execute("UPDATE worksheet SET status='approved' WHERE id=?", (ws_id,))
        con.commit()
        return []
    rules, now = config.settings()["levels"], datetime.now().isoformat(timespec="seconds")
    current = db.levels(con, ws["student"])
    tally = defaultdict(lambda: [0, 0, 0])  # skill -> [n, correct, too_easy]
    seen = set()
    for r in db.results(con, ws_id):
        if not r["scanned"] or r["excluded"]:
            continue
        seen.add(r["skill"])
        if r["kind"] in ("new", "placement"):
            t = tally[r["skill"]]
            t[0] += 1
            t[1] += bool(r["correct"])
            t[2] += bool(r["too_easy"])

    changes = []
    for skill_id, (n, k, easy) in tally.items():
        row = current[skill_id]
        before = State(row["level"], row["up_streak"], row["down_streak"], bool(row["mastered"]))
        max_level = len(config.skill(skill_id)["levels"])
        if ws["kind"] == "placement":
            after = placement_result(k, max_level)
        else:
            after = update(before, n, k, easy, rules, max_level)
        con.execute("""UPDATE skill_level SET level=?, up_streak=?, down_streak=?, mastered=?, updated_at=?
                       WHERE student=? AND skill=?""",
                    (after.level, after.up, after.down, int(after.mastered), now, ws["student"], skill_id))
        con.execute("INSERT OR REPLACE INTO session VALUES (?,?,?,?,?,?,?,?,?)",
                    (ws["student"], skill_id, ws["date"], ws_id, n, k, easy, before.level, after.level))
        name = config.skill(skill_id)["name"]
        if after.mastered and not before.mastered:
            changes.append(f"{name}: MASTERED")
        elif after.level != before.level:
            changes.append(f"{name}: level {before.level} -> {after.level}")
    for skill_id in seen:
        con.execute("UPDATE skill_level SET last_seen=? WHERE student=? AND skill=?", (ws["date"], ws["student"], skill_id))
    con.execute("UPDATE worksheet SET status='approved' WHERE id=?", (ws_id,))
    con.commit()
    return changes
