"""Verifiable event log: Merkle tree, signed checkpoints, inclusion and consistency proofs.

The event log is already a hash chain (each entry commits to the one before it). A chain proves
order, but checking one entry means replaying every entry. A Merkle tree over the same entries
(RFC 6962 / RFC 9162 hashing, as used by Certificate Transparency) gives two short proofs:

* inclusion   - this entry is in the log that has this root (about log2(n) hashes);
* consistency - a later log still contains an earlier one unchanged (append-only, nothing rewritten).

A checkpoint (tree size, root, time) is signed with this instance's Ed25519 key. Anyone holding a
checkpoint can check both proofs offline with scripts/verify_log_proof.py, without trusting this
server. A checkpoint that has been given to someone else (the client, a regulator, a timestamping
service) is what makes later rewriting detectable; the server cannot enforce that step itself.
"""
from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, HTTPException

from . import app as p1

router = APIRouter(prefix="/log", tags=["Verifiable event log"])
ORIGIN = "pramaan-event-log-v1"


def leaf_hash(entry_hash_hex: str) -> bytes:
    return hashlib.sha256(b"\x00" + bytes.fromhex(entry_hash_hex)).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(n: int) -> int:
    """Largest power of two strictly less than n (n > 1)."""
    return 1 << ((n - 1).bit_length() - 1)


def root(leaves: list[bytes]) -> bytes:
    if not leaves:
        return hashlib.sha256(b"").digest()
    if len(leaves) == 1:
        return leaves[0]
    k = _split(len(leaves))
    return _node(root(leaves[:k]), root(leaves[k:]))


def inclusion_path(index: int, leaves: list[bytes]) -> list[bytes]:
    if len(leaves) <= 1:
        return []
    k = _split(len(leaves))
    if index < k:
        return inclusion_path(index, leaves[:k]) + [root(leaves[k:])]
    return inclusion_path(index - k, leaves[k:]) + [root(leaves[:k])]


def consistency_path(first: int, leaves: list[bytes]) -> list[bytes]:
    """RFC 6962 section 2.1.2: proof that the first `first` leaves are a prefix of `leaves`."""
    def sub(m: int, part: list[bytes], whole: bool) -> list[bytes]:
        n = len(part)
        if m == n:
            return [] if whole else [root(part)]
        k = _split(n)
        if m <= k:
            return sub(m, part[:k], whole) + [root(part[k:])]
        return sub(m - k, part[k:], False) + [root(part[:k])]
    return [] if first in (0, len(leaves)) else sub(first, leaves, True)


def verify_inclusion(leaf: bytes, index: int, size: int, path: list[bytes], expected_root: bytes) -> bool:
    """RFC 9162 section 2.1.3.2."""
    if index >= size:
        return False
    fn, sn, r = index, size - 1, leaf
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = _node(p, r)
            if not fn & 1:
                while fn and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            r = _node(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == expected_root


def verify_consistency(first: int, second: int, first_root: bytes, second_root: bytes, path: list[bytes]) -> bool:
    """RFC 9162 section 2.1.4.2."""
    if first > second:
        return False
    if first == second:
        return not path and first_root == second_root
    if first == 0:
        return not path
    path = list(path)
    if first & (first - 1) == 0:
        path = [first_root] + path
    if not path:
        return False
    fn, sn = first - 1, second - 1
    while fn & 1:
        fn >>= 1
        sn >>= 1
    fr = sr = path[0]
    for c in path[1:]:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            fr, sr = _node(c, fr), _node(c, sr)
            if not fn & 1:
                while fn and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            sr = _node(sr, c)
        fn >>= 1
        sn >>= 1
    return sn == 0 and fr == first_root and sr == second_root


# ---------------------------------------------------------------- signing key and checkpoints

def _signing_key() -> Ed25519PrivateKey:
    """PRAMAAN_LOG_SIGNING_KEY (base64, 32 bytes) or a per-instance key kept beside the database."""
    configured = os.environ.get("PRAMAAN_LOG_SIGNING_KEY", "").strip()
    if configured:
        try:
            return Ed25519PrivateKey.from_private_bytes(base64.b64decode(configured, validate=True))
        except Exception as exc:
            raise HTTPException(500, "log signing key is not valid") from exc
    path = p1.ROOT / "log-signing.key"
    if not path.exists():
        p1.ROOT.mkdir(parents=True, exist_ok=True)
        raw = os.urandom(32)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(base64.b64encode(raw))
        except FileExistsError:
            pass
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(path.read_bytes().strip(), validate=True))


def checkpoint_body(size: int, root_hex: str, issued_at: str) -> bytes:
    return f"{ORIGIN}\n{size}\n{root_hex}\n{issued_at}\n".encode()


def _leaves(db, size: int | None = None) -> list[bytes]:
    rows = db.execute("SELECT entry_hash FROM events ORDER BY seq" + (" LIMIT ?" if size is not None else ""), (size,) if size is not None else ()).fetchall()
    return [leaf_hash(r[0]) for r in rows]


def _checkpoint(leaves: list[bytes]) -> dict[str, Any]:
    key = _signing_key()
    issued = datetime.now(timezone.utc).isoformat(timespec="seconds")
    root_hex = root(leaves).hex()
    return {"origin": ORIGIN, "tree_size": len(leaves), "root_hash": root_hex, "issued_at": issued,
            "public_key": base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
            "signature": base64.b64encode(key.sign(checkpoint_body(len(leaves), root_hex, issued))).decode()}


def verify_checkpoint(checkpoint: dict[str, Any], trusted_public_key_b64: str | None = None) -> bool:
    try:
        public = trusted_public_key_b64 or checkpoint["public_key"]
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public, validate=True)).verify(
            base64.b64decode(checkpoint["signature"], validate=True),
            checkpoint_body(int(checkpoint["tree_size"]), checkpoint["root_hash"], checkpoint["issued_at"]))
        return True
    except Exception:
        return False


@router.get("/checkpoint")
def log_checkpoint() -> dict[str, Any]:
    """Signed statement of the log's current size and Merkle root. Keep a copy outside this system."""
    db = p1.connect()
    try:
        return _checkpoint(_leaves(db))
    finally:
        db.close()


@router.get("/proof")
def log_inclusion_proof(seq: int | None = None, entry_hash: str | None = None) -> dict[str, Any]:
    """Proof that one log entry is in the log described by the returned checkpoint."""
    db = p1.connect()
    try:
        rows = db.execute("SELECT seq, entry_hash, prev_hash, event_json FROM events ORDER BY seq").fetchall()
        index = next((i for i, r in enumerate(rows) if r["seq"] == seq or (entry_hash and r["entry_hash"] == entry_hash)), None)
        if index is None:
            raise HTTPException(404, "log entry not found")
        leaves = [leaf_hash(r["entry_hash"]) for r in rows]
        return {"seq": rows[index]["seq"], "leaf_index": index, "entry_hash": rows[index]["entry_hash"], "prev_hash": rows[index]["prev_hash"], "event_json": rows[index]["event_json"],
                "inclusion_path": [h.hex() for h in inclusion_path(index, leaves)], "checkpoint": _checkpoint(leaves)}
    finally:
        db.close()


@router.get("/consistency")
def log_consistency_proof(first: int) -> dict[str, Any]:
    """Proof that the log of `first` entries (from an earlier checkpoint) is an unchanged prefix of today's log."""
    db = p1.connect()
    try:
        leaves = _leaves(db)
        if first < 0 or first > len(leaves):
            raise HTTPException(422, "first must be between 0 and the current tree size")
        return {"first_tree_size": first, "first_root_hash": root(leaves[:first]).hex(),
                "consistency_path": [h.hex() for h in consistency_path(first, leaves)], "checkpoint": _checkpoint(leaves)}
    finally:
        db.close()
