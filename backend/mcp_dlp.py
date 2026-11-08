"""MCP egress data-loss-prevention (DLP) layer.

Why this exists: the MCP tool results are the one place where the company's
business data crosses the trust boundary into a third-party AI agent (judge's
ChatGPT/Claude/Gemini/Groq). Even with correct authorization, letting raw
customer identifiers and financial-account numbers flow verbatim to an external
model is a data-leak the company cannot audit or retract. This layer sits at the
MCP boundary and, before any tool result reaches the model:

  1. REDACTS sensitive identifiers by default (GSTIN, PAN, bank account, phone,
     email) to typed placeholders, so the agent can still reason over structure
     and relationships without ever seeing the raw value; and
  2. DENIES (blocks the whole result) when a configured high-sensitivity category
     appears -- by default bank/financial account numbers -- so those never leave
     the server even masked; and
  3. produces a REPORT (categories + counts + field paths, never raw values) that
     the server appends to the hash-chained audit log, giving the company an
     auditable record of exactly what the AI was prevented from seeing.

Deterministic, dependency-free, and pure: easy to unit-test and to reason about.
This narrows egress; it is not a substitute for the server-side authorization and
role boundaries, which still apply to every call.
"""
from __future__ import annotations

import re
from typing import Any

# Patterns are deliberately conservative to avoid masking structural ids/hashes.
PATTERNS: dict[str, re.Pattern[str]] = {
    # India GSTIN: 2-digit state + 10-char PAN + entity + 'Z' + checksum
    "gstin": re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b"),
    # PAN: 5 letters + 4 digits + 1 letter
    "pan": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    # Standalone 11-18 digit run = bank/financial account number (not adjacent to
    # other alphanumerics, so it will not fire inside hex hashes or GSTINs).
    "bank_account": re.compile(r"(?<![0-9A-Za-z])\d{11,18}(?![0-9A-Za-z])"),
    # Indian mobile: optional +91/0 prefix then a 10-digit number starting 6-9.
    "phone": re.compile(r"(?<![0-9A-Za-z])(?:\+91[-\s]?|0)?[6-9]\d{9}(?![0-9A-Za-z])"),
}

# Key names whose values are structural ids/hashes and must never be filtered.
SKIP_KEYS = frozenset({
    "run_id", "finding_id", "object_ref", "snapshot_hash", "current_hash",
    "source_manifest_sha256", "ruleset_hash", "sha256", "entry_hash", "prev_hash",
    "payload_hash", "head", "random_draw", "selection_digest", "request_id",
    "evidence_id", "dataset_id", "signed_qr_envelope", "key_id",
})
_HEX = re.compile(r"\A[0-9a-f]{32,}\Z")

# PRAMAAN's own identifiers end in a hex fragment (REG-ee6b3cf26582, F3-c7133b50c34c29, P3-...).
# Now and then that fragment is all digits (about 1 in 280 for 12 hex characters), which looked like
# a bank account number and withheld the whole result. A digit run that directly follows one of
# these prefixes is an identifier, not an account, so it is left alone.
_ID_PREFIX = re.compile(r"(?<![0-9A-Za-z])(?:REG|RP|BANK|ACT|INV-AG|P3|F3|ER|ER-AG|P5)-\Z")

# Digit-only categories that an identifier's hex fragment can resemble.
_ID_CATEGORIES = frozenset({"bank_account", "phone"})


def _is_identifier(text: str, start: int) -> bool:
    return bool(_ID_PREFIX.search(text, max(0, start - 8), start))


def default_policy() -> dict[str, Any]:
    """Live policy: redact every category, hard-deny financial account numbers."""
    return {"redact": set(PATTERNS), "deny": {"bank_account"}, "mask": "[REDACTED:{category}]"}


class DeniedByPolicy(Exception):
    """Raised when a tool result contains a deny-listed category; the whole result is withheld."""

    def __init__(self, categories: list[str], report: dict[str, Any]):
        super().__init__("DENIED: response withheld by egress policy")
        self.categories = categories
        self.report = report


def _scan(text: str, policy: dict[str, Any], counts: dict[str, int], hit_deny: set[str]) -> str:
    if _HEX.match(text):
        return text
    masked = text
    for category in sorted(policy["redact"]):
        pattern = PATTERNS[category]
        mask = policy["mask"].format(category=category.upper())
        hits = 0

        def replace(match: re.Match[str], source: str = masked) -> str:
            nonlocal hits
            if category in _ID_CATEGORIES and _is_identifier(source, match.start()):
                return match.group(0)
            hits += 1
            return mask
        masked = pattern.sub(replace, masked)
        if not hits:
            continue
        counts[category] = counts.get(category, 0) + hits
        if category in policy.get("deny", set()):
            hit_deny.add(category)
    return masked


def _walk(node: Any, policy: dict[str, Any], path: str, counts: dict[str, int],
          fields: set[str], hit_deny: set[str]) -> Any:
    if isinstance(node, dict):
        return {key: (node[key] if key in SKIP_KEYS else _walk(node[key], policy, path + "/" + str(key), counts, fields, hit_deny)) for key in node}
    if isinstance(node, list):
        return [_walk(item, policy, path + "/" + str(index), counts, fields, hit_deny) for index, item in enumerate(node)]
    if isinstance(node, str):
        masked = _scan(node, policy, counts, hit_deny)
        if masked != node:
            fields.add(path)
        return masked
    return node


def apply_egress_policy(data: Any, tool: str, policy: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
    """Filter a tool result before it crosses to the AI. Returns (filtered_data, report).

    Raises DeniedByPolicy if a deny-listed category appears anywhere in the result.
    """
    policy = policy or default_policy()
    counts: dict[str, int] = {}
    fields: set[str] = set()
    hit_deny: set[str] = set()
    filtered = _walk(data, policy, "", counts, fields, hit_deny)
    report = {"tool": tool, "redaction_counts": counts, "fields_filtered": sorted(fields),
              "denied": bool(hit_deny), "denied_categories": sorted(hit_deny),
              "total_redactions": sum(counts.values())}
    if hit_deny:
        raise DeniedByPolicy(sorted(hit_deny), report)
    return filtered, report
