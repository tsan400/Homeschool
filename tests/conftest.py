import pytest

from hs import accounts, db, vault


@pytest.fixture
def con(tmp_path, monkeypatch):
    """A fresh portal home (database, files/) with a master key."""
    monkeypatch.setenv("HS_HOME", str(tmp_path))
    monkeypatch.setenv(vault.ENV, vault.keygen())
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def family(con):
    """One family with two children, like the original brief."""
    fid = accounts.create_family(con, "Test family")
    kids = {"timothy": accounts.add_student(con, fid, "Timothy", 4, 5),
            "hannah": accounts.add_student(con, fid, "Hannah", 7, 7)}
    return fid, kids
