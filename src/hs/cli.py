"""The `hs` command."""

from datetime import date as Date
from pathlib import Path

import typer

from hs import config, db, grade as grading, levels, planner, render, review as reviewing, vault

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Personal homeschool engine.")


def setup():
    con = db.connect()
    for s in config.students().values():
        levels.seed(con, s)
    return con


@app.command("print")
def print_(student: str = typer.Option(None, help="Only this student (default: all)."),
           date: str = typer.Option(None, help="YYYY-MM-DD (default: today)."),
           placement: bool = typer.Option(False, help="Print a placement packet instead of the daily one."),
           test: bool = typer.Option(False, help="Print a calibration packet (never changes levels)."),
           fresh: bool = typer.Option(False, help="Discard an unscanned packet for this day and make a new one.")):
    """Make today's packet and answer key for each child."""
    con = setup()
    date = date or Date.today().isoformat()
    kind = "placement" if placement else "test" if test else "daily"
    targets = ["test"] if test else [student] if student else list(config.students())
    for sid in targets:
        if not test and sid not in config.students():
            raise typer.BadParameter(f"unknown student {sid}")
        pending = con.execute("SELECT id FROM worksheet WHERE student=? AND status IN ('graded','partial') AND date < ?", (sid, date)).fetchall()
        if pending:
            typer.secho(f"{sid}: {len(pending)} graded packet(s) not approved yet; using last approved levels. Run `hs review`.", fg="yellow")
        ws_id = f"{date}-{sid}-math" + ("" if kind == "daily" else f"-{kind}")
        existing = db.worksheet(con, ws_id)
        if existing and fresh:
            if existing["status"] != "printed":
                raise typer.BadParameter(f"{ws_id} has already been scanned; not replacing it")
            con.execute("UPDATE response SET scaffolded=0 WHERE problem_id IN (SELECT source_problem_id FROM problem WHERE worksheet_id=?)", (ws_id,))
            con.execute("DELETE FROM problem WHERE worksheet_id=?", (ws_id,))
            con.execute("DELETE FROM worksheet WHERE id=?", (ws_id,))
            existing = None
        if not existing:
            planner.create(con, sid, date, kind)
        packet, key = render.render(con, ws_id, config.day_dir(date, sid))
        n = len(db.problems(con, ws_id))
        typer.echo(f"{sid}: {n} problems -> {packet}  (key: {key.name})")


@app.command()
def grade(scans: list[str] = typer.Argument(None, help="Scan PDFs or images (default: everything in inbox/).")):
    """Read and grade scanned pages. Inbox scans are encrypted, then the originals are shredded."""
    setup()
    inbox = config.inbox_dir()
    paths = [Path(s) for s in scans] if scans else sorted(
        p for p in inbox.glob("*") if p.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".enc"))
    if not paths:
        typer.echo(f"No scans found in {inbox}")
        return
    try:
        vault.key()
    except vault.VaultError as e:
        raise typer.BadParameter(str(e)) from None
    for path in paths:
        typer.secho(path.name, bold=True)
        for line in grading.ingest(path):
            typer.echo(line)
    typer.echo("Next: hs review")


@app.command()
def keygen():
    """Print a new key for encrypting scans. Set it as HS_SCAN_KEY and keep a copy safe."""
    typer.echo(vault.keygen())
    typer.echo("\nAdd to your shell profile:  export HS_SCAN_KEY=<the key above>\n"
               "Keep a copy in your password manager: without it, saved scans and crops can't be opened.", err=True)


@app.command()
def review(student: str = typer.Option(None), open_images: bool = typer.Option(True, "--open/--no-open", help="Open each flagged answer image.")):
    """Confirm flagged answers and approve graded packets (levels update only here)."""
    setup()
    reviewing.run(student, open_images)


@app.command()
def status(student: str = typer.Option(None)):
    """Current levels and anything waiting for review."""
    con = setup()
    for sid, s in config.students().items():
        if student and sid != student:
            continue
        lv = db.levels(con, sid)
        mastered = sum(r["mastered"] for r in lv.values())
        typer.secho(f"\n{s['name']}: {mastered}/{len(lv)} math skills mastered", bold=True)
        active = [sk for sk in config.skills() if not lv[sk["id"]]["mastered"]][: config.settings()["math"]["active_skills"]]
        for sk in active:
            r = lv[sk["id"]]
            typer.echo(f"   {sk['name']}: level {r['level']} ({sk['levels'][r['level'] - 1]}), {r['up_streak']} good sessions in a row")
        waiting = con.execute("SELECT id, status FROM worksheet WHERE student=? AND status IN ('printed','graded','partial') ORDER BY date", (sid,)).fetchall()
        for w in waiting:
            typer.echo(f"   {w['id']}: {w['status']}")


@app.command()
def curriculum(grade: list[int] = typer.Option(None, help="Only these grades (0 = K). Repeatable.")):
    """The K-12 math sequence. * = generated and graded by the engine; the rest are not yet."""
    auto = {sk["id"] for sk in config.skills()}
    for g in config.curriculum():
        if grade and g["grade"] not in grade:
            continue
        typer.secho(f"\n{g['label']}  ({'; '.join(g['sources'])})", bold=True)
        for t in g["topics"]:
            typer.echo(f"  {'*' if t['id'] in auto else ' '} {t['name']}  [{t['mode']}]")
