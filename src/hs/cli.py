"""The `hs` command: run the portal and a few admin tasks. Families do everything else in the portal."""

import os

import typer

from hs import accounts, config, db, vault

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Homeschool engine and parent portal.")


@app.command()
def serve(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(int(os.environ.get("PORT", 8000))),
          reload: bool = typer.Option(False, help="Restart on code changes (development).")):
    """Run the parent portal."""
    import uvicorn
    try:
        vault.master_key()
    except vault.VaultError as e:
        raise typer.BadParameter(str(e)) from None
    uvicorn.run("hs.web:create_app", factory=True, host=host, port=port, reload=reload,
                proxy_headers=True, forwarded_allow_ips="*")


@app.command()
def invite(email: str):
    """Let an email address sign in and start a new family."""
    con = db.connect()
    accounts.invite(con, email)
    typer.echo(f"Invited {accounts.normalize(email)}. They sign in at {config.base_url()}/signin")


@app.command()
def families():
    """List families (no children's data)."""
    con = db.connect()
    for f in con.execute("""SELECT f.id, f.name, f.created_at, GROUP_CONCAT(p.email, ', ') AS emails,
            (SELECT COUNT(*) FROM student s WHERE s.family_id = f.id) AS kids
            FROM family f LEFT JOIN parent p ON p.family_id = f.id GROUP BY f.id"""):
        typer.echo(f"{f['id']:>4}  {f['name']}  ({f['kids']} children)  {f['emails']}  since {f['created_at'][:10]}")
    pending = [r["email"] for r in con.execute("SELECT email FROM invite WHERE family_id IS NULL")]
    if pending:
        typer.echo("Invited, not signed in yet: " + ", ".join(pending))


@app.command()
def keygen():
    """Print a new master key. Set it as HS_MASTER_KEY on the server and keep a copy safe."""
    typer.echo(vault.keygen())
    typer.echo("\nStore it as the HS_MASTER_KEY secret on your host, and keep a copy in a password manager.\n"
               "Without it, no saved scan or packet can be opened.", err=True)


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
