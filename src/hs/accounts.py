"""Families, parents, children, invitations and email sign-in links."""

import hashlib
import re
import secrets
import shutil
from datetime import datetime, timedelta

from hs import config, db, levels, vault

LINK_MINUTES = 20


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))


def invite(con, email: str, family_id: int | None = None):
    """Allow an email to sign in. With family_id, they join that family; otherwise they start their own."""
    email = normalize(email)
    if not valid_email(email):
        raise ValueError(f"not an email address: {email!r}")
    con.execute("INSERT OR REPLACE INTO invite VALUES (?,?,?)", (email, family_id, now()))
    con.commit()


def parent(con, email: str):
    return con.execute("SELECT * FROM parent WHERE email=?", (normalize(email),)).fetchone()


def may_sign_in(con, email: str) -> bool:
    email = normalize(email)
    return bool(parent(con, email) or con.execute("SELECT 1 FROM invite WHERE email=?", (email,)).fetchone())


def create_family(con, name: str) -> int:
    cur = con.execute("INSERT INTO family (name, key_wrapped, created_at) VALUES (?, x'', ?)", (name, now()))
    fid = cur.lastrowid
    con.execute("UPDATE family SET key_wrapped=? WHERE id=?", (vault.new_family_key(fid), fid))
    con.commit()
    return fid


def accept(con, email: str):
    """First sign-in of an invited email: join the inviting family or start a new one."""
    email = normalize(email)
    if p := parent(con, email):
        return p
    inv = con.execute("SELECT * FROM invite WHERE email=?", (email,)).fetchone()
    if inv is None:
        return None
    fid = inv["family_id"] or create_family(con, email.split("@")[0].title() + " family")
    con.execute("INSERT INTO parent (family_id, email, created_at) VALUES (?,?,?)", (fid, email, now()))
    con.execute("DELETE FROM invite WHERE email=?", (email,))
    con.commit()
    return parent(con, email)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def make_login_token(con, email: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(minutes=LINK_MINUTES)).isoformat(timespec="seconds")
    con.execute("DELETE FROM login_token WHERE expires_at < ?", (now(),))
    con.execute("INSERT INTO login_token VALUES (?,?,?,0)", (_hash(token), normalize(email), expires))
    con.commit()
    return token


def use_login_token(con, token: str):
    """Single use, short lived. Returns the parent row, or None."""
    row = con.execute("SELECT * FROM login_token WHERE hash=?", (_hash(token),)).fetchone()
    if row is None or row["used"] or row["expires_at"] < now():
        return None
    con.execute("UPDATE login_token SET used=1 WHERE hash=?", (row["hash"],))
    con.commit()
    return accept(con, row["email"])


def recent_links(con, email: str, minutes: int = 10) -> int:
    since = (datetime.now() + timedelta(minutes=LINK_MINUTES - minutes)).isoformat(timespec="seconds")
    return con.execute("SELECT COUNT(*) FROM login_token WHERE email=? AND expires_at > ?",
                       (normalize(email), since)).fetchone()[0]


def add_student(con, family_id: int, name: str, grade: int, math_grade: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())[:16] or "child"
    sid = f"{slug}-{secrets.token_hex(2)}"
    con.execute("INSERT INTO student VALUES (?,?,?,?,?,?)", (sid, family_id, name.strip(), grade, math_grade, now()))
    levels.seed(con, db.student(con, sid))
    return sid


def delete_family(con, family_id: int):
    """Remove a family and everything about it: rows (cascade) and encrypted files."""
    con.execute("DELETE FROM family WHERE id=?", (family_id,))
    con.commit()
    shutil.rmtree(config.files_dir() / str(family_id), ignore_errors=True)
