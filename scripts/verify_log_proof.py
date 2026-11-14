#!/usr/bin/env python3
"""Check a PRAMAAN event-log proof offline. Standard library only (signature check needs `cryptography`).

  python scripts/verify_log_proof.py inclusion proof.json [--public-key BASE64]
  python scripts/verify_log_proof.py consistency consistency.json --earlier old_checkpoint.json

proof.json       = the JSON returned by GET /log/proof?seq=N
consistency.json = the JSON returned by GET /log/consistency?first=SIZE
old_checkpoint   = a checkpoint (GET /log/checkpoint) you saved earlier; SIZE is its tree_size

Exit code 0 means every check passed. Pass --public-key with the key you obtained from the audit
firm through another channel; without it the signature is only checked against the key inside the
file, which shows the file is self-consistent but not who signed it.
"""
import argparse
import base64
import hashlib
import json
import sys


def node(left, right):
    return hashlib.sha256(b"\x01" + left + right).digest()


def verify_inclusion(leaf, index, size, path, root):
    if index >= size:
        return False
    fn, sn, r = index, size - 1, leaf
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = node(p, r)
            if not fn & 1:
                while fn and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            r = node(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == root


def verify_consistency(first, second, first_root, second_root, path):
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
            fr, sr = node(c, fr), node(c, sr)
            if not fn & 1:
                while fn and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            sr = node(sr, c)
        fn >>= 1
        sn >>= 1
    return sn == 0 and fr == first_root and sr == second_root


def signature_ok(checkpoint, public_key):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return None
    body = f"{checkpoint['origin']}\n{checkpoint['tree_size']}\n{checkpoint['root_hash']}\n{checkpoint['issued_at']}\n".encode()
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key or checkpoint["public_key"])).verify(base64.b64decode(checkpoint["signature"]), body)
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=["inclusion", "consistency"])
    parser.add_argument("file")
    parser.add_argument("--earlier", help="earlier checkpoint JSON (consistency)")
    parser.add_argument("--public-key", help="trusted Ed25519 public key, base64")
    args = parser.parse_args()
    data = json.load(open(args.file, encoding="utf-8"))
    checkpoint = data["checkpoint"]
    checks = {}
    signed = signature_ok(checkpoint, args.public_key)
    checks["checkpoint signature" + ("" if args.public_key else " (key from the file itself)")] = signed
    if args.kind == "inclusion":
        checks["entry hash matches the event text"] = hashlib.sha256(bytes.fromhex(data["prev_hash"]) + data["event_json"].encode("utf-8")).hexdigest() == data["entry_hash"]
        leaf = hashlib.sha256(b"\x00" + bytes.fromhex(data["entry_hash"])).digest()
        checks["entry is included under the signed root"] = verify_inclusion(leaf, data["leaf_index"], checkpoint["tree_size"], [bytes.fromhex(h) for h in data["inclusion_path"]], bytes.fromhex(checkpoint["root_hash"]))
    else:
        if not args.earlier:
            parser.error("consistency needs --earlier old_checkpoint.json")
        old = json.load(open(args.earlier, encoding="utf-8"))
        old = old.get("checkpoint", old)
        checks["earlier checkpoint signature"] = signature_ok(old, args.public_key)
        checks["sizes match the earlier checkpoint"] = old["tree_size"] == data["first_tree_size"]
        checks["today's log still contains the earlier log unchanged"] = verify_consistency(old["tree_size"], checkpoint["tree_size"], bytes.fromhex(old["root_hash"]), bytes.fromhex(checkpoint["root_hash"]), [bytes.fromhex(h) for h in data["consistency_path"]])
    failed = False
    for name, result in checks.items():
        print(("PASS" if result else "SKIP (install `cryptography`)" if result is None else "FAIL").ljust(30), name)
        failed |= result is False
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
