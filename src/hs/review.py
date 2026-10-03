"""`hs review`: confirm flagged reads, override grades, then approve so levels update."""

import re

import typer

from hs import config, db, grade, levels

HELP = "[Enter] ok  [t] type what was written  [c] correct  [w] wrong  [s] stuck  [e] too easy  [x] exclude  [q] quit"


def plain(markup: str) -> str:
    """Typst prompt -> terminal text."""
    t = markup.replace("\\$", "\x00").replace("$", "").replace("\x00", "$")
    for a, b in ((" times ", " × "), (" div ", " ÷ "), ("square", "□"), ("thin ", "")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def show(r):
    sk = config.skill(r["skill"])["name"]
    typer.secho(f"\n#{r['number']} (page {r['page']})  {sk}, level {r['level']} [{r['kind']}]", bold=True)
    typer.echo(f"   Problem: {plain(r['prompt'])}")
    typer.echo(f"   Key:     {r['answer']}")
    if not r["scanned"]:
        typer.secho("   Not scanned yet.", fg="yellow")
        return
    if r["excluded"]:
        typer.secho("   Excluded from scoring.", fg="yellow")
        return
    verdict = typer.style("CORRECT", fg="green") if r["correct"] else typer.style("WRONG", fg="red")
    read = "(blank)" if r["blank"] else f'"{r["transcription"]}"  (confidence {r["confidence"]:.2f})'
    typer.echo(f"   Read:    {read}  -> {verdict}")
    typer.echo(f"   Marks:   stuck {'●' if r['stuck'] else '○'}  too easy {'●' if r['too_easy'] else '○'}"
               f"   (fill {r['stuck_fill']:.2f} / {r['easy_fill']:.2f})")
    if r["reason"]:
        typer.secho(f"   Why:     {r['reason']}", fg="yellow")


def set_(con, pid, **cols):
    sql = ", ".join(f"{k}=?" for k in cols)
    con.execute(f"UPDATE response SET {sql} WHERE problem_id=?", (*cols.values(), pid))
    con.commit()


def edit(con, ws_id, number, open_images) -> bool:
    """Interactive edit of one problem. Returns False if the user quit."""
    row = lambda: next(r for r in db.results(con, ws_id) if r["number"] == number)
    r = row()
    if open_images and r["scanned"] and r["crop"]:
        typer.launch(r["crop"])
    while True:
        show(r)
        if not r["scanned"]:
            choice = typer.prompt("   [x] exclude from today's score  [Enter] skip (rescan later)  [q] quit",
                                  default="", show_default=False).strip().lower()
            if choice == "x":
                con.execute("INSERT INTO response (problem_id, excluded, reviewed, correct, stuck, too_easy) VALUES (?,1,1,0,0,0)", (r["id"],))
                con.commit()
            return choice != "q"
        choice = typer.prompt("   " + HELP, default="", show_default=False).strip().lower()
        pid = r["id"]
        if choice == "":
            set_(con, pid, reviewed=1)
            return True
        if choice == "q":
            return False
        if choice == "x":
            set_(con, pid, excluded=1, reviewed=1)
            return True
        if choice == "t":
            text = typer.prompt("   What did the child write?")
            ok = grade.check(text, r["answer"], r["form"])
            if ok is None:
                ok = typer.confirm("   Can't parse that. Count it as correct?")
            set_(con, pid, transcription=text, confidence=1.0, blank=int(not text.strip()), correct=int(ok))
        elif choice in ("c", "w"):
            set_(con, pid, correct=int(choice == "c"))
        elif choice == "s":
            set_(con, pid, stuck=int(not r["stuck"]))
        elif choice == "e":
            set_(con, pid, too_easy=int(not r["too_easy"]))
        r = row()


def summary(rows):
    counted = [r for r in rows if r["scanned"] and not r["excluded"]]
    typer.secho(f"\nScore: {sum(r['correct'] for r in counted)}/{len(counted)}", bold=True)
    by_skill = {}
    for r in counted:
        t = by_skill.setdefault((r["skill"], r["kind"]), [0, 0, 0])
        t[0] += 1
        t[1] += r["correct"]
        t[2] += r["stuck"]
    for (sk, kind), (n, k, stuck) in by_skill.items():
        typer.echo(f"   {config.skill(sk)['name']} [{kind}]: {k}/{n}" + (f", {stuck} stuck" if stuck else ""))
    wrong = [r for r in counted if not r["correct"]]
    if wrong:
        typer.echo("   Wrong: " + ", ".join(f"#{r['number']} wrote {r['transcription'] or '(blank)'!r} (key {r['answer']})" for r in wrong))


def run(student: str | None = None, open_images: bool = True):
    con = db.connect()
    sql = "SELECT * FROM worksheet WHERE status IN ('graded', 'partial')" + (" AND student=?" if student else "") + " ORDER BY date, student"
    worksheets = con.execute(sql, (student,) if student else ()).fetchall()
    if not worksheets:
        typer.echo("Nothing to review.")
        return
    for ws in worksheets:
        typer.secho(f"\n=== {ws['id']} ({ws['status']}) ===", bold=True, fg="cyan")
        for r in db.results(con, ws["id"]):
            needs = (r["scanned"] and r["reason"] and not r["reviewed"]) or not r["scanned"]
            if needs and not edit(con, ws["id"], r["number"], open_images):
                return
        while True:
            rows = db.results(con, ws["id"])
            summary(rows)
            missing = [r["number"] for r in rows if not r["scanned"]]
            if missing:
                typer.secho(f"   Not scanned: {missing}. Scan them or exclude them before approving.", fg="yellow")
            choice = typer.prompt("Approve and update levels? [y] yes  [n] not now  [number] edit a problem",
                                  default="n").strip().lower()
            if choice.isdigit():
                if not edit(con, ws["id"], int(choice), open_images):
                    return
                continue
            if choice == "y" and not missing:
                grade.write_grades(con, ws["id"])
                changes = levels.approve(con, ws["id"])
                grade.write_grades(con, ws["id"])
                typer.secho("Approved. " + ("; ".join(changes) if changes else "No level changes."), fg="green")
            break
