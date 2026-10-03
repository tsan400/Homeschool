"""Encryption for scan images. Scans and crops only ever reach disk through here.

AES-256-GCM with a key from the HS_SCAN_KEY environment variable (create one with
`hs keygen`). Each file is MAGIC + 12-byte nonce + ciphertext. The file's label (e.g.
"2026-10-05-timothy-math/crop/07") is bound in as associated data, so an encrypted
crop can't be swapped for another without detection.
"""

import base64
import os
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"HSE1"
ENV = "HS_SCAN_KEY"


class VaultError(Exception):
    pass


def keygen() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def key() -> bytes:
    raw = os.environ.get(ENV)
    if not raw:
        raise VaultError(f"{ENV} is not set. Run `hs keygen` once and keep the key somewhere safe "
                         "(password manager); without it, saved scans can't be opened.")
    try:
        k = base64.urlsafe_b64decode(raw)
    except ValueError:
        k = b""
    if len(k) != 32:
        raise VaultError(f"{ENV} must be a key made by `hs keygen` (32 bytes, base64)")
    return k


def encrypt(data: bytes, label: str) -> bytes:
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(key()).encrypt(nonce, data, label.encode())


def decrypt(blob: bytes, label: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise VaultError("not an encrypted hs file")
    try:
        return AESGCM(key()).decrypt(blob[4:16], blob[16:], label.encode())
    except InvalidTag:
        raise VaultError(f"can't decrypt {label}: wrong HS_SCAN_KEY, or the file was altered") from None


def save(path: Path, data: bytes, label: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypt(data, label))


def load(path: Path, label: str) -> bytes:
    return decrypt(Path(path).read_bytes(), label)


def shred(path: Path):
    """Overwrite then delete a plaintext file. Best effort: SSDs and copy-on-write
    filesystems may keep old blocks, so the real protection is never writing plaintext."""
    path = Path(path)
    try:
        with open(path, "r+b") as f:
            f.write(b"\0" * path.stat().st_size)
            f.flush()
            os.fsync(f.fileno())
    finally:
        path.unlink(missing_ok=True)
