"""Create a machine-readable local release-evidence manifest.

This is not a substitute for a security audit or independent audit review. It
records the exact evaluated synthetic fixture, ruleset, core implementation
hashes, and measured evaluation output so a reviewer can reproduce a release
claim from the same checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from . import evaluate

ROOT = Path(__file__).resolve().parent
TRACKED_INPUTS = (
    "app.py", "p2.py", "p3.py", "p3_crypto.py", "p4.py", "p5.py",
    "p5_checks.py", "p5_exports.py", "security.py", "mcp_server.py",
    "mcp_dlp.py", "upload_safety.py", "release_verify.py", "p3_ruleset.yaml", "ruleset.yaml",
)


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(created_at: str | None = None) -> dict:
    report = evaluate.run_evaluation()
    source_manifest = ROOT.parent / "data" / "source_manifest.json"
    files = {name: sha256_path(ROOT / name) for name in TRACKED_INPUTS}
    result = {
        "schema_version": "pramaan-release-evidence-v1",
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "scope": "local synthetic prototype verification",
        "evaluation": report,
        "dataset_manifest_sha256": sha256_path(source_manifest),
        "implementation_sha256": files,
        "limitations": [
            "Synthetic evaluation only; no real-world accuracy claim.",
            "This manifest does not prove external anchoring, source authenticity, or production security.",
            "Independent-person blind rehearsal evidence is not created by this command.",
        ],
    }
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    return {**result, "manifest_sha256": hashlib.sha256(encoded).hexdigest()}


def require_quality(manifest: dict) -> None:
    report = manifest["evaluation"]
    if report["pramaan_caught_A"] != report["planted_total_X"]:
        raise SystemExit("release evidence failed: planted irregularities were missed")
    if report["false_alarms_on_innocent_C"] != 0:
        raise SystemExit("release evidence failed: hard-conflict false alarms are present")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Pramaan local release-evidence JSON")
    parser.add_argument("--output", type=Path, help="Explicit file to receive JSON; otherwise writes stdout")
    parser.add_argument("--require-quality", action="store_true", help="Exit non-zero unless current synthetic quality gates pass")
    args = parser.parse_args()
    manifest = build_manifest()
    if args.require_quality:
        require_quality(manifest)
    text = json.dumps(manifest, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
