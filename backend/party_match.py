"""Deterministic, local party-name matching (AgentX F2).

Runs entirely on the server. Raw party names never leave this process: callers get a
score, a band and normalised forms only when they are permitted to see them (the agent
tools return the band and score, never the names).
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Bands are configuration, not model judgement.
MATCH_THRESHOLD = 0.92
POSSIBLE_THRESHOLD = 0.75

# Honorifics and legal-form words carry no identity.
_DROP = {"m", "s", "ms", "mr", "mrs", "shri", "smt", "messrs", "the",
         "pvt", "private", "ltd", "limited", "llp", "inc", "co", "company", "corp", "corporation"}
# Common abbreviations in Indian invoices and bank narrations, mapped to one canonical token.
_CANON = {"trdrs": "traders", "trdr": "traders", "trader": "traders", "tradrs": "traders",
          "ent": "enterprises", "entp": "enterprises", "enterprise": "enterprises",
          "inds": "industries", "ind": "industries", "industry": "industries",
          "mfg": "manufacturing", "manufacturers": "manufacturing", "manufacturer": "manufacturing",
          "intl": "international", "bros": "brothers", "agcy": "agency", "agencies": "agency",
          "retl": "retail", "rtl": "retail", "dist": "distributors", "distributor": "distributors", "whls": "wholesale"}


def normalise(name: str | None) -> str:
    """Lower-case, strip accents and punctuation, drop honorifics/legal forms, canonicalise abbreviations."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\([^)]*\)", " ", text).replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", text)
    out = []
    for token in tokens:
        if token in _DROP or token == "and":
            continue
        out.append(_CANON.get(token, token))
    return " ".join(out)


def _token_similarity(a: str, b: str) -> float:
    """Best per-token pairing using character similarity, so 'trdrs' still aligns with 'traders'."""
    ta, tb = a.split(), b.split()
    if not ta or not tb:
        return 0.0
    def side(x, y):
        return sum(max(SequenceMatcher(None, t, u).ratio() for u in y) for t in x) / len(x)
    return min(side(ta, tb), side(tb, ta))


def score(name_a: str | None, name_b: str | None) -> float:
    a, b = normalise(name_a), normalise(name_b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Different numbers in a name (branch 1 vs branch 2, unit numbers) mean different parties.
    digits_a, digits_b = set(re.findall(r"\d+", a)), set(re.findall(r"\d+", b))
    if digits_a != digits_b and (digits_a or digits_b):
        return round(min(0.5, SequenceMatcher(None, a, b).ratio()), 4)
    whole = SequenceMatcher(None, a, b).ratio()
    sorted_whole = SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio()
    return round(max(whole, sorted_whole, _token_similarity(a, b)), 4)


def band(value: float) -> str:
    if value >= MATCH_THRESHOLD:
        return "match"
    if value >= POSSIBLE_THRESHOLD:
        return "possible_match"
    return "no_match"


def compare(name_a: str | None, name_b: str | None) -> dict:
    value = score(name_a, name_b)
    return {"score": value, "band": band(value), "thresholds": {"match": MATCH_THRESHOLD, "possible_match": POSSIBLE_THRESHOLD},
            "normalised": [normalise(name_a), normalise(name_b)],
            "needs_human_confirmation": band(value) == "possible_match"}
