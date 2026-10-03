import pytest

from hs import accounts, config, vault


def test_round_trip_and_label_binding():
    key = bytes(32)
    blob = vault.encrypt(b"\x89PNG secret", "1/ws/a/crop-01.png", key)
    assert b"secret" not in blob
    assert vault.decrypt(blob, "1/ws/a/crop-01.png", key) == b"\x89PNG secret"
    with pytest.raises(vault.VaultError):
        vault.decrypt(blob, "1/ws/a/crop-02.png", key)      # can't pass one file off as another


def test_tampering_detected():
    blob = bytearray(vault.encrypt(b"data", "x", bytes(32)))
    blob[-1] ^= 1
    with pytest.raises(vault.VaultError):
        vault.decrypt(bytes(blob), "x", bytes(32))


def test_files_are_encrypted_per_family(con):
    a, b = accounts.create_family(con, "A"), accounts.create_family(con, "B")
    vault.put(con, a, "ws/x/page-1.jpg", b"\xff\xd8 page image")
    on_disk = (config.files_dir() / str(a) / "ws/x/page-1.jpg").read_bytes()
    assert on_disk.startswith(vault.MAGIC) and b"page image" not in on_disk
    assert vault.get(con, a, "ws/x/page-1.jpg") == b"\xff\xd8 page image"
    assert vault.family_key(con, a) != vault.family_key(con, b)
    # Family B's key can't open family A's file, even if it were copied across.
    dest = config.files_dir() / str(b) / "ws/x/page-1.jpg"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(on_disk)
    with pytest.raises(vault.VaultError):
        vault.get(con, b, "ws/x/page-1.jpg")


def test_wrong_or_missing_master_key(con, monkeypatch):
    fid = accounts.create_family(con, "A")
    vault.put(con, fid, "f", b"data")
    monkeypatch.setenv(vault.ENV, vault.keygen())
    with pytest.raises(vault.VaultError, match="wrong key"):
        vault.get(con, fid, "f")
    monkeypatch.setenv(vault.ENV, "not-a-key")
    with pytest.raises(vault.VaultError):
        vault.master_key()
    monkeypatch.delenv(vault.ENV)
    with pytest.raises(vault.VaultError, match="hs keygen"):
        vault.master_key()


def test_bad_names_refused():
    with pytest.raises(vault.VaultError):
        vault.path(1, "../2/ws/x")
