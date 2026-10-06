"""The parent portal, through HTTP: sign in, print, upload, calendar, day view, review, approve,
and above all that one family can never see another family's children or scans."""

import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from hs import accounts, db, mail, packets, vault, web
from synthetic import fill_in, layout_of, phone_scan, to_pdf
from test_scan_synthetic import reader_for

DAY = (date.today() - timedelta(days=3)).isoformat()   # in the past, so "not turned in"
MONTH = DAY[:7]


def sign_in(client, con, email):
    mail.outbox.clear()
    assert client.post("/signin", data={"email": email}).status_code == 200
    link = re.search(r"/signin/(\S+)", mail.outbox[-1]["text"])[1]
    assert client.get(f"/signin/{link}").status_code == 200        # confirm page, not yet signed in
    r = client.post(f"/signin/{link}", follow_redirects=False)
    assert r.status_code == 303
    return link


@pytest.fixture
def portal(con):
    accounts.invite(con, "mom@example.com")
    state = {}
    app = web.create_app(transcribe=lambda items: state["reader"](items), background=False)
    with TestClient(app, base_url="http://testserver") as client:
        yield client, state


def test_sign_in_is_invite_only_and_links_work_once(con, portal):
    client, _ = portal
    mail.outbox.clear()
    client.post("/signin", data={"email": "stranger@example.com"})
    assert mail.outbox == []                                      # no email, same response
    assert client.get("/", follow_redirects=False).headers["location"] == "/signin"

    link = sign_in(client, con, "Mom@Example.com")
    assert "Mom family" in client.get("/").text
    client.post("/signout")
    r = client.post(f"/signin/{link}")                             # reused link
    assert "expired or was already used" in r.text
    assert client.get("/", follow_redirects=False).status_code == 303


def add_kid(client, name, grade, math_grade):
    r = client.post("/students", data={"name": name, "grade": grade, "math_grade": math_grade}, follow_redirects=False)
    return r.headers["location"].split("/")[-1]


def test_print_upload_calendar_scan_review_approve(con, portal):
    client, state = portal
    sign_in(client, con, "mom@example.com")
    sid = add_kid(client, "Timothy", 4, 5)
    add_kid(client, "Hannah", 7, 7)

    # Print: make the packet for a day and download it.
    client.post(f"/students/{sid}/{DAY}/packet")
    ws_id = packets.ws_id(sid, DAY)
    pdf = client.get(f"/ws/{ws_id}/packet.pdf")
    assert pdf.content.startswith(b"%PDF") and "no-store" in pdf.headers["cache-control"]
    assert client.get(f"/ws/{ws_id}/key.pdf").content.startswith(b"%PDF")
    page = client.get(f"/students/{sid}?month={MONTH}").text
    assert "Not turned in" in page                                 # past date, nothing scanned

    # Fill in and upload; everything right except #2.
    probs = {p["number"]: p for p in db.problems(con, ws_id)}
    written = {n: ("999" if n == 2 else p["answer"]) for n, p in probs.items()}
    answers = {(p["page"], p["slot"]): written[n] for n, p in probs.items()}
    scan = to_pdf([phone_scan(img, i) for i, img in enumerate(fill_in(pdf.content, answers, {}, layout=layout_of(con, ws_id)))])
    state["reader"] = reader_for(probs, written)
    r = client.post("/uploads", files={"files": ("scan.pdf", scan, "application/pdf")})
    assert "graded" in r.text and f"{len(probs) - 1}/{len(probs)} correct" in r.text

    # Calendar shows it's ready to check; the day page shows the scanned pages and crops.
    assert "To check" in client.get(f"/students/{sid}?month={MONTH}").text
    day = client.get(f"/students/{sid}/{DAY}").text
    img = re.search(rf'/ws/{ws_id}/page-(\d+)\.jpg', day)
    assert img and client.get(img[0]).content.startswith(b"\xff\xd8")
    assert client.get(f"/ws/{ws_id}/crop-1.png").content.startswith(b"\x89PNG")

    # Review: the parent re-reads #2 as the right answer, then approves.
    form = {"action": "approve"}
    for p in probs.values():
        form[f"t{p['id']}"] = p["answer"] if p["number"] == 2 else written[p["number"]]
        form[f"c{p['id']}"] = "0" if p["number"] == 2 else "1"   # stale select; the new reading wins
    client.post(f"/ws/{ws_id}/review", data=form)
    assert db.worksheet(con, ws_id)["status"] == "approved"
    assert all(r["correct"] for r in db.results(con, ws_id))
    assert f"✓ {len(probs)}/{len(probs)}" in client.get(f"/students/{sid}?month={MONTH}").text

    # The one-click morning PDF has both children's packets.
    assert client.get("/today.pdf").content.startswith(b"%PDF")


def test_families_are_isolated(con, portal):
    client, _ = portal
    sign_in(client, con, "mom@example.com")
    sid = add_kid(client, "Timothy", 4, 5)
    client.post(f"/students/{sid}/{DAY}/packet")
    ws_id = packets.ws_id(sid, DAY)

    other = TestClient(client.app, base_url="http://testserver")
    accounts.invite(con, "other@example.com")
    sign_in(other, con, "other@example.com")
    for url in (f"/students/{sid}", f"/students/{sid}/{DAY}", f"/ws/{ws_id}/packet.pdf", f"/ws/{ws_id}/key.pdf",
                f"/ws/{ws_id}/page-1.jpg", f"/ws/{ws_id}/crop-1.png"):
        assert other.get(url).status_code == 404, url
    assert other.post(f"/students/{sid}/{DAY}/packet").status_code == 404
    assert other.post(f"/ws/{ws_id}/review", data={"action": "approve"}).status_code == 404
    assert "Timothy" not in other.get("/").text


def test_cross_site_post_refused(con, portal):
    client, _ = portal
    r = client.post("/signin", data={"email": "mom@example.com"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_invite_co_parent_and_delete_family(con, portal, tmp_path):
    client, _ = portal
    sign_in(client, con, "mom@example.com")
    sid = add_kid(client, "Timothy", 4, 5)
    client.post(f"/students/{sid}/{DAY}/packet")
    client.post("/family/invite", data={"email": "dad@example.com"})
    dad = TestClient(client.app, base_url="http://testserver")
    sign_in(dad, con, "dad@example.com")
    assert "Timothy" in dad.get("/").text                          # same family

    fid = db.student(con, sid)["family_id"]
    assert vault.path(fid, "x").parent.exists()
    client.post("/family/delete", data={"confirm": "DELETE"})
    assert db.student(con, sid) is None
    assert con.execute("SELECT COUNT(*) FROM problem").fetchone()[0] == 0
    assert not vault.path(fid, "x").parent.exists()
    assert dad.get("/", follow_redirects=False).status_code == 303   # session points at a deleted parent
