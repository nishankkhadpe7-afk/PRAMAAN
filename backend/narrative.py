"""AI narrative drafting with a hard citation validator.

The pitch's promise - "AI drafts explanations, but every sentence must point to
real evidence or it's rejected" - is enforced here, deterministically:

  1. An LLM drafts a plain-language explanation of a finding, instructed to cite
     only identifiers from an ALLOWED list in [square brackets].
  2. `validate_narrative` then splits the draft into sentences and DROPS any
     sentence that cites nothing, or that cites an identifier not in the allowed
     set (a hallucinated reference). Only validated sentences survive.
  3. If nothing validates, a deterministic fallback built from the finding's own
     reason + id is used - the system never emits an uncited claim.

The validator is pure and offline-testable; only the drafting step calls the LLM
(e.g. Groq), reusing the agent_llm config/poster.
"""
from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from . import agent_llm

CITATION = re.compile(r"\[([A-Za-z0-9:_\-/.]+)\]")

SYSTEM = (
    "You explain one audit finding to a human auditor in one or two plain sentences. "
    "Every sentence MUST cite at least one identifier from the ALLOWED list, in square brackets, e.g. [F3-ab12cd]. "
    "Cite ONLY identifiers from the allowed list - never invent one. "
    "State only what the finding supports; do not assert fraud or a conclusion. A human confirms outcomes."
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]


def valid_ids_for(finding: dict[str, Any], extra: tuple[str, ...] = ()) -> set[str]:
    ids = {finding.get("finding_id"), finding.get("object_ref")}
    ids |= set(finding.get("evidence_ids") or [])
    ids |= set(finding.get("cycle_edge_ids") or [])
    ids |= set(finding.get("invoice_ids") or [])
    ids |= set(extra)
    return {i for i in ids if i}


def validate_narrative(text: str, allowed_ids) -> dict[str, Any]:
    """Keep only sentences that cite at least one allowed identifier; drop the rest."""
    allowed = set(allowed_ids)
    accepted, rejected = [], []
    for sentence in _sentences(text):
        cites = CITATION.findall(sentence)
        if not cites:
            rejected.append({"sentence": sentence, "reason": "no evidence citation"})
        elif not all(c in allowed for c in cites):
            bad = [c for c in cites if c not in allowed]
            rejected.append({"sentence": sentence, "reason": "unresolved citation(s): " + ", ".join(bad)})
        else:
            accepted.append({"sentence": sentence, "citations": cites})
    return {"accepted": accepted, "rejected": rejected,
            "all_valid": bool(accepted) and not rejected,
            "validated_text": " ".join(a["sentence"] for a in accepted)}


async def _chat(cfg: dict[str, str], messages: list[dict[str, Any]],
                poster: Callable[[dict[str, str], dict[str, Any]], Awaitable[dict[str, Any]]]) -> str:
    data = await poster(cfg, {"model": cfg["model"], "messages": messages, "temperature": 0})
    return data["choices"][0]["message"].get("content", "") or ""


async def draft_narrative(finding: dict[str, Any], allowed_ids=None, cfg: dict[str, str] | None = None,
                          poster: Callable[[dict[str, str], dict[str, Any]], Awaitable[dict[str, Any]]] | None = None) -> dict[str, Any]:
    cfg = cfg or agent_llm.config()
    poster = poster or agent_llm._default_poster
    allowed = set(allowed_ids) if allowed_ids is not None else valid_ids_for(finding)
    prompt = ("Finding JSON:\n" + json.dumps(finding) + "\n\nALLOWED identifiers: " + ", ".join(sorted(allowed))
              + "\nWrite the explanation now, citing only allowed identifiers in [brackets].")
    draft = await _chat(cfg, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], poster)
    result = validate_narrative(draft, allowed)
    result["draft"] = draft
    if not result["accepted"]:
        anchor = finding.get("finding_id") or finding.get("object_ref") or ""
        fallback = (finding.get("reason", "").rstrip(".") + f". [{anchor}]") if anchor else ""
        result = validate_narrative(fallback, allowed | {anchor})
        result["draft"] = draft
        result["used_fallback"] = True
    result["model"] = cfg.get("model")
    return result
