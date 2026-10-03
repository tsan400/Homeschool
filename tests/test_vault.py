import urllib.error
import urllib.request

import pytest

from hs import vault
from hs.viewer import Viewer


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(vault.ENV, vault.keygen())


def test_round_trip_and_label_binding():
    blob = vault.encrypt(b"\x89PNG secret", "ws/crop/01")
    assert b"secret" not in blob
    assert vault.decrypt(blob, "ws/crop/01") == b"\x89PNG secret"
    with pytest.raises(vault.VaultError):
        vault.decrypt(blob, "ws/crop/02")       # can't pass one crop off as another


def test_wrong_or_missing_key(monkeypatch):
    blob = vault.encrypt(b"data", "x")
    monkeypatch.setenv(vault.ENV, vault.keygen())
    with pytest.raises(vault.VaultError, match="wrong HS_SCAN_KEY"):
        vault.decrypt(blob, "x")
    monkeypatch.setenv(vault.ENV, "not-a-key")
    with pytest.raises(vault.VaultError):
        vault.key()
    monkeypatch.delenv(vault.ENV)
    with pytest.raises(vault.VaultError, match="hs keygen"):
        vault.key()


def test_tampering_detected():
    blob = bytearray(vault.encrypt(b"data", "x"))
    blob[-1] ^= 1
    with pytest.raises(vault.VaultError):
        vault.decrypt(bytes(blob), "x")


def test_shred(tmp_path):
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF plaintext")
    vault.shred(f)
    assert not f.exists()


def test_viewer_serves_from_memory_without_caching():
    v = Viewer(open_browser=False)
    try:
        v.show(b"\x89PNG fake", "caption")
        with urllib.request.urlopen(v.url + "crop.png") as r:
            assert r.read() == b"\x89PNG fake"
            assert "no-store" in r.headers["Cache-Control"]
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(v.url.replace(v.token, "guess") + "crop.png")
    finally:
        v.close()
