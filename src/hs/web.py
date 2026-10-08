"""The parent portal: sign in, print packets, upload scans, see each child's calendar, review and approve.

Every page is scoped to the signed-in parent's family; anything belonging to another family is a 404.
Files are decrypted only to answer a request and are sent with no-store headers.
"""

import calendar
import hashlib
import hmac
import io
import json
import re
from contextlib import asynccontextmanager
from datetime import date as Date, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, available_timezones

import pypdfium2 as pdfium
from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from hs import accounts, config, db, grade, jobs, levels, mail, packets, read, readings, scan, vault, weather, words

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
KINDS = {"daily": "Daily packet", "placement": "Placement", "test": "Practice page"}
NO_STORE = {"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache"}


class NotSignedIn(Exception):
    pass


# ---------- helpers ----------

def plain(markup: str) -> str:
    """Typst prompt -> readable text."""
    t = markup.replace("\\$", "\x00").replace("$", "").replace("\x00", "$")
    for a, b in ((" times ", " × "), (" div ", " ÷ "), ("square", "□"), ("thin ", "")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def today(family) -> Date:
    return datetime.now(ZoneInfo(family["tz"])).date()


def score(rows) -> tuple[int, int]:
    counted = [r for r in rows if r["scanned"] and not r["excluded"]]
    return sum(bool(r["correct"]) for r in counted), len(counted)


def day_state(ws: dict, today_: Date) -> tuple[str, str, str]:
    """(css class, label, one-character label for small calendars) for a worksheet."""
    s = ws["status"]
    if s == "approved":
        return "done", f"✓ {ws['correct']}/{ws['counted']}" if ws["counted"] else "✓", "✓"
    if s == "graded":
        return "review", "To check", "?"
    if s == "partial":
        return "partial", "Pages missing", "½"
    if ws["date"] < today_.isoformat():
        return "missing", "Not turned in", "✗"
    return "assigned", "Assigned", "•"


def month_worksheets(con, sid, first: Date, last: Date) -> dict[str, list[dict]]:
    rows = con.execute("""SELECT w.id, w.date, w.kind, w.status,
            SUM(CASE WHEN r.problem_id IS NOT NULL AND r.excluded=0 THEN 1 ELSE 0 END) AS counted,
            SUM(CASE WHEN r.excluded=0 AND r.correct=1 THEN 1 ELSE 0 END) AS correct
        FROM worksheet w LEFT JOIN problem p ON p.worksheet_id = w.id LEFT JOIN response r ON r.problem_id = p.id
        WHERE w.student=? AND w.date BETWEEN ? AND ? GROUP BY w.id ORDER BY w.kind != 'daily'""",
                       (sid, first.isoformat(), last.isoformat())).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["date"], []).append(dict(r))
    return out


def month_view(con, student, month: str | None, today_: Date) -> dict:
    """Weeks of days (Sunday first) with each day's worksheets and state."""
    year, mon = (int(x) for x in month.split("-")) if month else (today_.year, today_.month)
    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, mon)
    by_day = month_worksheets(con, student["id"], weeks[0][0], weeks[-1][-1])
    cells = [[{"date": d, "in_month": d.month == mon, "today": d == today_,
               "sheets": [{**w, "state": day_state(w, today_), "kind_label": KINDS[w["kind"]]}
                         for w in by_day.get(d.isoformat(), [])]} for d in week] for week in weeks]
    prev = Date(year - (mon == 1), (mon - 2) % 12 + 1, 1)
    nxt = Date(year + (mon == 12), mon % 12 + 1, 1)
    return {"weeks": cells, "title": Date(year, mon, 1).strftime("%B %Y"),
            "prev": prev.strftime("%Y-%m"), "next": nxt.strftime("%Y-%m")}


def pdf_response(data: bytes, filename: str) -> Response:
    return Response(data, media_type="application/pdf",
                    headers={**NO_STORE, "Content-Disposition": f'inline; filename="{filename}"'})


# ---------- app ----------

def create_app(transcribe=read.transcribe, background: bool = True) -> FastAPI:
    vault.master_key()  # refuse to start without it
    con = db.connect()
    for s in con.execute("SELECT * FROM student").fetchall():
        levels.seed(con, s)  # children get level rows for any skills added since they joined
    con.close()

    @asynccontextmanager
    async def lifespan(app):
        if background:
            app.state.worker = jobs.Worker(transcribe)
            app.state.worker.start()
        yield
        if background:
            app.state.worker.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    secret = hmac.new(vault.master_key(), b"session cookie", hashlib.sha256).hexdigest()
    app.add_middleware(SessionMiddleware, secret_key=secret, max_age=30 * 24 * 3600, same_site="lax",
                       https_only=config.base_url().startswith("https://"))

    @app.middleware("http")
    async def same_origin_posts(request: Request, call_next):
        """Reject form posts from other sites (on top of the SameSite cookie)."""
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return Response("Cross-site request refused", status_code=403)
        return await call_next(request)

    @app.exception_handler(NotSignedIn)
    async def to_signin(request, exc):
        return RedirectResponse("/signin", status_code=303)

    def get_con():
        con = db.connect()
        try:
            yield con
        finally:
            con.close()

    def me(request: Request, con=Depends(get_con)):
        pid = request.session.get("parent")
        row = pid and con.execute("""SELECT p.id, p.email, p.family_id, f.name AS family_name, f.tz, f.place
                                     FROM parent p JOIN family f ON f.id = p.family_id WHERE p.id=?""", (pid,)).fetchone()
        if not row:
            request.session.clear()
            raise NotSignedIn
        return row

    def own_student(con, parent, sid):
        s = db.student(con, sid)
        if s is None or s["family_id"] != parent["family_id"]:
            raise HTTPException(404)
        return s

    def own_ws(con, parent, ws_id):
        if db.family_of_worksheet(con, ws_id) != parent["family_id"]:
            raise HTTPException(404)
        return db.worksheet(con, ws_id)

    def page(request, name, **ctx):
        return TEMPLATES.TemplateResponse(request, name, ctx, headers=NO_STORE)

    def back(url):
        return RedirectResponse(url, status_code=303)

    # ----- sign in -----

    @app.get("/signin", response_class=HTMLResponse)
    def signin_form(request: Request):
        return page(request, "signin.html", sent=False)

    @app.post("/signin", response_class=HTMLResponse)
    def signin_send(request: Request, email: str = Form(...), con=Depends(get_con)):
        email = accounts.normalize(email)
        if accounts.may_sign_in(con, email) and accounts.recent_links(con, email) < 5:
            token = accounts.make_login_token(con, email)
            mail.send(email, "Your Homeschool sign-in link",
                      f"Sign in to Homeschool:\n\n{config.base_url()}/signin/{token}\n\n"
                      f"The link works once and expires in {accounts.LINK_MINUTES} minutes. "
                      "If you didn't ask for it, ignore this email.")
        return page(request, "signin.html", sent=True)  # same answer either way: no account probing

    @app.get("/signin/{token}", response_class=HTMLResponse)
    def signin_confirm(request: Request, token: str):
        # A button, not an automatic sign-in: email link scanners would otherwise use up the link.
        return page(request, "signin_confirm.html", token=token)

    @app.post("/signin/{token}")
    def signin_use(request: Request, token: str, con=Depends(get_con)):
        parent = accounts.use_login_token(con, token)
        if parent is None:
            return page(request, "signin.html", sent=False, error="That link has expired or was already used. Ask for a new one.")
        request.session.clear()
        request.session["parent"] = parent["id"]
        return back("/")

    @app.post("/signout")
    def signout(request: Request):
        request.session.clear()
        return back("/signin")

    # ----- home -----

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, con=Depends(get_con), parent=Depends(me)):
        t = today(parent)
        kids = []
        for s in db.students(con, parent["family_id"]):
            daily = db.worksheet(con, packets.ws_id(s["id"], t.isoformat()))
            kids.append({"s": s, "today": daily, "cal": month_view(con, s, None, t)})
        to_check = con.execute("""SELECT w.*, s.name FROM worksheet w JOIN student s ON s.id = w.student
            WHERE s.family_id=? AND w.status IN ('graded','partial') ORDER BY w.date""", (parent["family_id"],)).fetchall()
        uploads = con.execute("SELECT * FROM upload WHERE family_id=? ORDER BY id DESC LIMIT 5", (parent["family_id"],)).fetchall()
        return page(request, "home.html", parent=parent, kids=kids, to_check=to_check, uploads=uploads, today=t)

    @app.get("/today.pdf")
    def today_pdf(con=Depends(get_con), parent=Depends(me)):
        """Every child's packet for today in one PDF, made if needed: one click to print in the morning."""
        t = today(parent).isoformat()
        merged = pdfium.PdfDocument.new()
        for s in db.students(con, parent["family_id"]):
            wid = packets.make(con, s["id"], t)
            merged.import_pages(pdfium.PdfDocument(vault.get(con, parent["family_id"], packets.packet_name(wid))))
        if len(merged) == 0:
            raise HTTPException(404, "Add a child first")
        buf = io.BytesIO()
        merged.save(buf)
        return pdf_response(buf.getvalue(), f"packets-{t}.pdf")

    # ----- children -----

    @app.get("/students/{sid}", response_class=HTMLResponse)
    def student_page(request: Request, sid: str, month: str | None = None, con=Depends(get_con), parent=Depends(me)):
        s = own_student(con, parent, sid)
        t = today(parent)
        lv = db.levels(con, sid)
        active = [(sk, lv[sk["id"]]) for sk in config.skills() if sk["id"] in lv and not lv[sk["id"]]["mastered"]]
        n_mastered = sum(r["mastered"] for r in lv.values())
        return page(request, "student.html", parent=parent, s=s, cal=month_view(con, s, month, t), today=t,
                    active=active[: config.settings()["math"]["active_skills"]], upcoming=active[3:8],
                    n_mastered=n_mastered, n_skills=len(lv))

    @app.get("/students/{sid}/{day}", response_class=HTMLResponse)
    def day_page(request: Request, sid: str, day: str, con=Depends(get_con), parent=Depends(me)):
        s = own_student(con, parent, sid)
        try:
            d = Date.fromisoformat(day)
        except ValueError:
            raise HTTPException(404)
        sheets = []
        for ws in con.execute("SELECT * FROM worksheet WHERE student=? AND date=? ORDER BY kind != 'daily'", (sid, day)):
            rows = db.results(con, ws["id"])
            sheets.append({"ws": ws, "kind": KINDS[ws["kind"]], "rows": rows, "score": score(rows),
                           "pages": json.loads(ws["scanned_pages"]), "extras": extras_view(con, ws),
                           "skill": {r["skill"]: config.skill(r["skill"])["name"] for r in rows},
                           "missing": [r["number"] for r in rows if not r["scanned"]]})
        pending = con.execute("SELECT COUNT(*) FROM worksheet WHERE student=? AND status IN ('graded','partial') AND date < ?",
                              (sid, day)).fetchone()[0]
        return page(request, "day.html", parent=parent, s=s, d=d, day=day, sheets=sheets, plain=plain,
                    pending=pending, today=today(parent))

    def extras_view(con, ws) -> dict:
        """The word, the weather, the reading and French for a packet, for the day page."""
        out = {"weather": json.loads(ws["weather"]) if ws["weather"] else None, "word": None, "reading": None, "french": None}
        scanned = set(json.loads(ws["scanned_pages"]))
        for subject, a in db.assignments(con, ws["id"]).items():
            if subject == "word":
                out["word"] = words.entry(a["item"])
            elif subject == "french":
                unclear = a["fill"] is not None and scan.BUBBLE_EMPTY < a["fill"] < scan.BUBBLE_MARKED
                out["french"] = {"label": readings.french_label(a["item"]), "done": a["done"], "unclear": unclear}
            else:
                r = readings.reading(a["item"])
                out["reading"] = {"subject": readings.SUBJECTS[subject], "key": subject, "book": r["book"], "title": r["title"],
                                  "week": r["week"], "page": a["page"], "scanned": a["page"] in scanned, "done": a["done"]}
        return out

    @app.post("/students/{sid}/{day}/packet")
    def make_packet(sid: str, day: str, kind: str = Form("daily"), fresh: bool = Form(False),
                    con=Depends(get_con), parent=Depends(me)):
        own_student(con, parent, sid)
        try:
            Date.fromisoformat(day)
        except ValueError:
            raise HTTPException(404)
        if kind not in KINDS:
            raise HTTPException(400)
        try:
            packets.make(con, sid, day, kind, fresh)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return back(f"/students/{sid}/{day}")

    # ----- files (decrypted on request, never cached) -----

    @app.get("/ws/{ws_id}/{what}.pdf")
    def ws_pdf(ws_id: str, what: str, con=Depends(get_con), parent=Depends(me)):
        ws = own_ws(con, parent, ws_id)
        if what not in ("packet", "key"):
            raise HTTPException(404)
        name = (packets.packet_name if what == "packet" else packets.key_name)(ws_id)
        if not vault.exists(parent["family_id"], name):
            packets.make(con, ws["student"], ws["date"], ws["kind"])
        return pdf_response(vault.get(con, parent["family_id"], name), f"{ws_id}-{what}.pdf")

    @app.get("/ws/{ws_id}/page-{n}.jpg")
    def ws_page(ws_id: str, n: int, con=Depends(get_con), parent=Depends(me)):
        own_ws(con, parent, ws_id)
        if not vault.exists(parent["family_id"], grade.page_name(ws_id, n)):
            raise HTTPException(404)
        return Response(vault.get(con, parent["family_id"], grade.page_name(ws_id, n)), media_type="image/jpeg", headers=NO_STORE)

    @app.get("/ws/{ws_id}/crop-{number}.png")
    def ws_crop(ws_id: str, number: int, con=Depends(get_con), parent=Depends(me)):
        own_ws(con, parent, ws_id)
        if not vault.exists(parent["family_id"], grade.crop_name(ws_id, number)):
            raise HTTPException(404)
        return Response(vault.get(con, parent["family_id"], grade.crop_name(ws_id, number)), media_type="image/png", headers=NO_STORE)

    # ----- review and approve -----

    @app.post("/ws/{ws_id}/review")
    async def review(request: Request, ws_id: str, con=Depends(get_con), parent=Depends(me)):
        ws = own_ws(con, parent, ws_id)
        if ws["status"] == "approved":
            raise HTTPException(409, "Already approved")
        form = await request.form()
        for r in db.results(con, ws_id):
            pid = r["id"]
            excluded = int(f"x{pid}" in form)
            if not r["scanned"]:
                if excluded:
                    con.execute("INSERT INTO response (problem_id, excluded, reviewed, correct, stuck, too_easy) VALUES (?,1,1,0,0,0)", (pid,))
                continue
            text = str(form.get(f"t{pid}", r["transcription"] or "")).strip()
            correct = form.get(f"c{pid}") == "1"
            if text != (r["transcription"] or "") and (auto := grade.check(text, r["answer"], r["form"], r["prompt"])) is not None:
                correct = auto  # the parent corrected the reading: re-grade it
            con.execute("""UPDATE response SET transcription=?, blank=?, correct=?, stuck=?, too_easy=?, excluded=?,
                           reviewed=1, confidence=CASE WHEN transcription=? THEN confidence ELSE 1.0 END WHERE problem_id=?""",
                        (text, int(not text), int(correct), int(f"s{pid}" in form), int(f"e{pid}" in form), excluded, text, pid))
        for subject in db.assignments(con, ws_id):
            if subject != "word":  # French lesson done; reading narrated (out loud counts)
                con.execute("UPDATE assignment SET done=? WHERE worksheet_id=? AND subject=?",
                            (int(f"done_{subject}" in form), ws_id, subject))
        con.commit()
        s = db.student(con, ws["student"])
        url = f"/students/{s['id']}/{ws['date']}"
        if form.get("action") == "approve":
            if any(not r["scanned"] for r in db.results(con, ws_id)):
                return back(url + "?msg=missing#" + ws_id)
            changes = levels.approve(con, ws_id)
            request.session["flash"] = "Approved. " + ("; ".join(changes) if changes else "No level changes.")
        return back(url + "#" + ws_id)

    # ----- uploads -----

    @app.get("/uploads", response_class=HTMLResponse)
    def uploads_page(request: Request, con=Depends(get_con), parent=Depends(me)):
        rows = con.execute("SELECT * FROM upload WHERE family_id=? ORDER BY id DESC LIMIT 30", (parent["family_id"],)).fetchall()
        return page(request, "uploads.html", parent=parent, uploads=rows,
                    busy=any(r["status"] == "queued" for r in rows), max_mb=config.settings()["max_upload_mb"])

    @app.post("/uploads")
    def upload(request: Request, files: list[UploadFile], con=Depends(get_con), parent=Depends(me)):
        limit = config.settings()["max_upload_mb"] * 1024 * 1024
        for f in files:
            data = f.file.read(limit + 1)
            if not data:
                continue
            if len(data) > limit:
                raise HTTPException(413, f"{f.filename} is larger than {limit // 2**20} MB")
            uid = jobs.submit(con, parent["family_id"], f.filename or "scan", data)
            if not background:
                jobs.process(con, uid, transcribe)
        if background:
            request.app.state.worker.wake()
        return back("/uploads")

    @app.post("/uploads/{uid}/retry")
    def upload_retry(request: Request, uid: int, con=Depends(get_con), parent=Depends(me)):
        up = con.execute("SELECT * FROM upload WHERE id=? AND family_id=?", (uid, parent["family_id"])).fetchone()
        if up is None or not vault.exists(parent["family_id"], jobs.upload_name(uid)):
            raise HTTPException(404)
        jobs.retry(con, uid)
        if background:
            request.app.state.worker.wake()
        else:
            jobs.process(con, uid, transcribe)
        return back("/uploads")

    # ----- family settings -----

    @app.get("/family", response_class=HTMLResponse)
    def family_page(request: Request, con=Depends(get_con), parent=Depends(me)):
        fid = parent["family_id"]
        return page(request, "family.html", parent=parent, kids=db.students(con, fid), ao_years=readings.years(),
                    parents=con.execute("SELECT * FROM parent WHERE family_id=?", (fid,)).fetchall(),
                    invites=con.execute("SELECT * FROM invite WHERE family_id=?", (fid,)).fetchall(),
                    zones=sorted(z for z in available_timezones() if "/" in z and not z.startswith("Etc")))

    @app.post("/family")
    def family_save(request: Request, name: str = Form(...), tz: str = Form(...), place: str = Form(""),
                    con=Depends(get_con), parent=Depends(me)):
        if tz not in available_timezones():
            raise HTTPException(400, "Unknown time zone")
        con.execute("UPDATE family SET name=?, tz=? WHERE id=?", (name.strip()[:80], tz, parent["family_id"]))
        place = place.strip()[:100]
        if not place:
            con.execute("UPDATE family SET place=NULL, lat=NULL, lon=NULL, units=NULL WHERE id=?", (parent["family_id"],))
        elif place != parent["place"]:
            try:
                found = weather.locate(place)
                con.execute("UPDATE family SET place=?, lat=?, lon=?, units=? WHERE id=?",
                            (found["place"], found["lat"], found["lon"], found["units"], parent["family_id"]))
                request.session["flash"] = f"Weather on packets will be for {found['place']}."
            except weather.WeatherError as e:
                request.session["flash"] = f"Weather not changed: {e}."
        con.commit()
        return back("/family")

    @app.post("/family/invite")
    def family_invite(email: str = Form(...), con=Depends(get_con), parent=Depends(me)):
        email = accounts.normalize(email)
        if accounts.parent(con, email):
            raise HTTPException(409, "That email already has an account")
        try:
            accounts.invite(con, email, parent["family_id"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        mail.send(email, "You're invited to Homeschool",
                  f"{parent['email']} invited you to their family's Homeschool portal.\n\n"
                  f"Sign in with this email address at {config.base_url()}/signin")
        return back("/family")

    def ao_year(value: str) -> int | None:
        if not value:
            return None
        if not value.isdigit() or int(value) not in readings.years():
            raise HTTPException(400, "Unknown AmblesideOnline year")
        return int(value)

    @app.post("/students")
    def student_add(name: str = Form(...), grade_: int = Form(..., alias="grade"), math_grade: int = Form(...),
                    ao: str = Form(""), french: bool = Form(False), con=Depends(get_con), parent=Depends(me)):
        if not name.strip() or not (0 <= grade_ <= 12 and 0 <= math_grade <= 12):
            raise HTTPException(400, "Name and grades 0-12 are required")
        sid = accounts.add_student(con, parent["family_id"], name[:40], grade_, math_grade, ao_year(ao), french)
        return back(f"/students/{sid}")

    @app.post("/students/{sid}")
    def student_edit(sid: str, name: str = Form(...), grade_: int = Form(..., alias="grade"),
                     ao: str = Form(""), french: bool = Form(False), con=Depends(get_con), parent=Depends(me)):
        own_student(con, parent, sid)
        if not name.strip() or not 0 <= grade_ <= 12:
            raise HTTPException(400, "Name and a grade 0-12 are required")
        con.execute("UPDATE student SET name=?, grade=?, ao_year=?, french=? WHERE id=?",
                    (name.strip()[:40], grade_, ao_year(ao), int(french), sid))
        con.commit()
        return back("/family")

    @app.post("/family/delete")
    def family_delete(request: Request, confirm: str = Form(""), con=Depends(get_con), parent=Depends(me)):
        if confirm.strip() != "DELETE":
            raise HTTPException(400, "Type DELETE to confirm")
        accounts.delete_family(con, parent["family_id"])
        request.session.clear()
        return back("/signin")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    TEMPLATES.env.globals["flash"] = lambda request: request.session.pop("flash", None)
    return app
