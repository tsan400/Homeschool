"""Make a child's packet for a day and keep its PDFs (encrypted) in the family's files."""

from hs import db, planner, render, vault


def packet_name(ws_id: str) -> str:
    return f"ws/{ws_id}/packet.pdf"


def key_name(ws_id: str) -> str:
    return f"ws/{ws_id}/key.pdf"


def ws_id(student: str, date: str, kind: str = "daily") -> str:
    return f"{date}-{student}-math" + ("" if kind == "daily" else f"-{kind}")


def make(con, student: str, date: str, kind: str = "daily", fresh: bool = False) -> str:
    """Create (or, with fresh, replace an unscanned) packet and store its PDFs. Returns the worksheet id."""
    family_id = db.student(con, student)["family_id"]
    wid = ws_id(student, date, kind)
    existing = db.worksheet(con, wid)
    if existing and fresh:
        if existing["status"] != "printed":
            raise ValueError("this packet has already been scanned, so it can't be replaced")
        con.execute("UPDATE response SET scaffolded=0 WHERE problem_id IN "
                    "(SELECT source_problem_id FROM problem WHERE worksheet_id=?)", (wid,))
        con.execute("DELETE FROM worksheet WHERE id=?", (wid,))  # problems cascade
        con.commit()
        existing = None
    if not existing:
        planner.create(con, student, date, kind)
    if fresh or not vault.exists(family_id, packet_name(wid)):
        packet, key = render.render(con, wid)
        vault.put(con, family_id, packet_name(wid), packet)
        vault.put(con, family_id, key_name(wid), key)
    return wid
