"""Encryption at rest for the evidence vault (AES-256-GCM).

Turned on by configuring a key, which must live OUTSIDE the data folder (a copied data folder must not carry its key):
  PRAMAAN_VAULT_KEY        base64url-encoded 32-byte key, or
  PRAMAAN_VAULT_KEY_FILE   path to a file holding that value (create one with: python -m backend.vault_tools new-key PATH)

A vault file keeps its name, the SHA-256 of the ORIGINAL bytes, so every integrity check still works on the decrypted
content. Encrypted files start with MAGIC; files without it are legacy plaintext and stay readable, so turning
encryption on is safe for an existing vault (`python -m backend.vault_tools encrypt` converts them, `decrypt` undoes it).
Layout: MAGIC | 12-byte random nonce | AES-GCM(ciphertext + tag), with the SHA-256 name as associated data, so a file
renamed or swapped for another fails to open.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path

MAGIC = b"PRMV1\x00"


class VaultKeyError(RuntimeError):
    """The vault holds encrypted files but no usable key is configured (or the key is wrong)."""


def _decode(text: str) -> bytes:
    value = base64.urlsafe_b64decode(text.strip() + "=" * (-len(text.strip()) % 4))
    if len(value) != 32:
        raise VaultKeyError("the vault key must be 32 bytes (base64url encoded)")
    return value


def configured_key(data_root: Path | None = None) -> bytes | None:
    """The vault key, or None when encryption at rest is not configured."""
    if os.environ.get("PRAMAAN_VAULT_KEY"):
        return _decode(os.environ["PRAMAAN_VAULT_KEY"])
    path = os.environ.get("PRAMAAN_VAULT_KEY_FILE")
    if not path:
        return None
    key_path = Path(path).expanduser().resolve()
    if data_root is not None:
        root = Path(data_root).resolve()
        if key_path == root or root in key_path.parents:
            raise VaultKeyError("the vault key file must be outside the data folder, so a copy of the data cannot be read without it")
    try:
        return _decode(key_path.read_text(encoding="ascii"))
    except FileNotFoundError as exc:
        raise VaultKeyError(f"vault key file not found: {key_path.name}") from exc


def fingerprint(key: bytes) -> str:
    """Safe to show or store: identifies a key without revealing it."""
    return hashlib.sha256(b"pramaan-vault-key:" + key).hexdigest()[:16]


def new_key_text() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def is_sealed(data: bytes) -> bool:
    return data.startswith(MAGIC)


def seal(sha: str, raw: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, raw, sha.encode())


def unseal(sha: str, data: bytes, key: bytes | None) -> bytes:
    """Plain bytes of a vault file: legacy plaintext is returned as is; encrypted files need the key."""
    if not is_sealed(data):
        return data
    if key is None:
        raise VaultKeyError("this evidence file is encrypted but no vault key is configured (PRAMAAN_VAULT_KEY_FILE)")
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        return AESGCM(key).decrypt(data[len(MAGIC):len(MAGIC) + 12], data[len(MAGIC) + 12:], sha.encode())
    except InvalidTag as exc:
        raise VaultKeyError("evidence file could not be decrypted: wrong vault key, or the file was altered") from exc
