"""What goes into a day's math."""

from hs import db, packets, planner


def test_practice_after_a_stuck_problem_is_never_above_the_childs_level(con, family):
    """A placement can move a skill back down after a problem in it was marked stuck at a
    higher level. The practice that follows its worked example comes at the child's level now."""
    fid, kids = family
    sid = kids["timothy"]
    p = db.problems(con, packets.make(con, sid, "2026-10-05"))[0]
    con.execute("UPDATE problem SET level=5 WHERE id=?", (p["id"],))
    con.execute("""INSERT INTO response (problem_id, stuck, too_easy, correct, reviewed, excluded, scaffolded)
                   VALUES (?,1,0,0,1,0,0)""", (p["id"],))
    con.execute("UPDATE skill_level SET level=1, mastered=0 WHERE student=? AND skill=?", (sid, p["skill"]))
    con.commit()
    specs, sources = planner.plan_daily(con, sid)
    assert sources == [p["id"]]
    assert [s["level"] for s in specs if s["kind"] == "scaffold"] == [1, 1]
