"""Encrypted file storage. Every file the portal keeps (scans, crops, packets) goes through here.

Envelope encryption with AES-256-GCM:
- HS_MASTER_KEY (from `hs keygen`, kept in the host's secret store) only wraps family keys.
- Each family has its own random key, stored wrapped in the database.
- Each file is MAGIC + 12-byte nonce + ciphertext, with its storage name bound in as associated
  data, so a file can't be swapped for another (or another family's) without detection.
A copy of the files directory or the database alone reveals nothing.
"""

import base64
import os
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hs import config

MAGIC = b"HSE1"
ENV = "HS_MASTER_KEY"


class VaultError(Exception):
    pass


def keygen() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def master_key() -> bytes:
    raw = os.environ.get(ENV)
    if not raw:
        raise VaultError(f"{ENV} is not set. Run `hs keygen` once and store the key as a secret on the host "
                         "(and in a password manager): without it, no saved file can be opened.")
    try:
        k = base64.urlsafe_b64decode(raw)
    except ValueError:
        k = b""
    if len(k) != 32:
        raise VaultError(f"{ENV} must be a key made by `hs keygen` (32 bytes, base64)")
    return k


def encrypt(data: bytes, label: str, key: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, label.encode())


def decrypt(blob: bytes, label: str, key: bytes) -> bytes:
    if not blob.startswith(MAGIC):
        raise VaultError("not an encrypted hs file")
    try:
        return AESGCM(key).decrypt(blob[4:16], blob[16:], label.encode())
    except InvalidTag:
        raise VaultError(f"can't decrypt {label}: wrong key, or the file was altered") from None


def new_family_key(family_id: int) -> bytes:
    """A fresh family key, wrapped with the master key for storage in the family row."""
    return encrypt(secrets.token_bytes(32), f"family/{family_id}", master_key())


def family_key(con, family_id: int) -> bytes:
    row = con.execute("SELECT key_wrapped FROM family WHERE id=?", (family_id,)).fetchone()
    if row is None:
        raise VaultError(f"no family {family_id}")
    return decrypt(row["key_wrapped"], f"family/{family_id}", master_key())


def path(family_id: int, name: str) -> Path:
    if ".." in name or name.startswith("/"):
        raise VaultError(f"bad file name {name}")
    return config.files_dir() / str(family_id) / name


def put(con, family_id: int, name: str, data: bytes):
    p = path(family_id, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(encrypt(data, f"{family_id}/{name}", family_key(con, family_id)))
    tmp.replace(p)  # atomic: a crash never leaves half a file


def get(con, family_id: int, name: str) -> bytes:
    return decrypt(path(family_id, name).read_bytes(), f"{family_id}/{name}", family_key(con, family_id))


def exists(family_id: int, name: str) -> bool:
    return path(family_id, name).exists()


def delete(family_id: int, name: str):
    path(family_id, name).unlink(missing_ok=True)
