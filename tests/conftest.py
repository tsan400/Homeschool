import pytest

from hs import config, db, levels, vault


@pytest.fixture
def con(tmp_path, monkeypatch):
    """A fresh engine home (database, data/, inbox/) with both students seeded."""
    monkeypatch.setenv("HS_HOME", str(tmp_path))
    monkeypatch.setenv(vault.ENV, vault.keygen())
    c = db.connect()
    for s in config.students().values():
        levels.seed(c, s)
    return c
