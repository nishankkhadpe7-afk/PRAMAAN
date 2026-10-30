"""T13 e-invoice signed-QR verification adapter.

Real Ed25519 signature verification of a signed e-invoice QR payload against a
*configured trusted key*, a cross-check of the signed fields with the books, and
a registration-timing risk signal.

Honesty constraints (see MASTER.md T13 / A4, principle 6):
- The bundled key is a clearly labelled DEMO key, NOT a government (NIC/IRP) key.
  A `DEMO_IRP_TEST_ONLY` key can only yield `GOVERNMENT_REGISTERED_DEMO`; it never
  sets `externally_verified` or `government_registered` True. To verify against the
  real portal, drop the official public key and key_id into the ruleset `t13` block
  with `key_classification="OFFICIAL_IRP"`; no code change is required.
- A later acknowledgement date is a *backdating-risk indicator to investigate*,
  never proof, and never produces `IMPOSSIBLE`.
- Verification is deterministic: no wall-clock, no network. The adapter proves only
  what the signature and the covered payload fields can support.
"""
from __future__ import annotations

import base64
import json
from datetime import date
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# --- DEMO KEY MATERIAL -- TEST ONLY -- NOT A GOVERNMENT / NIC / IRP KEY ---------
# Deterministically derived from a fixed, labelled seed so the synthetic signed
# fixtures are reproducible. Never present this as official verification.
DEMO_IRP_KEY_ID = "pramaan-demo-irp-ed25519-1"
DEMO_IRP_PUBLIC_KEY_B64 = "4IHzKlJTcNVckWV2q9zfpQGfD1u9hslMtu7MXfUCLs4="
DEMO_IRP_PRIVATE_KEY_B64 = "UFJBTUFBTi1ERU1PLUlSUC1FRDI1NTE5LVNFRUQwMDE="  # DEMO ONLY
DEMO_IRP_KEY_CLASSIFICATION = "DEMO_IRP_TEST_ONLY"

COVERED_FIELDS = ("irn", "bill_no", "buyer_gstin", "seller_gstin", "gross_cents", "hsn_code", "invoice_date")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_envelope(payload: dict[str, Any], private_key_b64: str = DEMO_IRP_PRIVATE_KEY_B64) -> str:
    """Produce a base64 signed-QR envelope. Used to build demo fixtures and tests only."""
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64, validate=True))
    signature = key.sign(_canonical(payload))
    envelope = {"payload": payload, "signature_base64": base64.b64encode(signature).decode()}
    return base64.b64encode(_canonical(envelope)).decode()


def _parse_iso(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def verify_einvoice(envelope_b64: str | None, trusted_public_key_b64: str, key_id: str,
                    key_classification: str, book_fields: dict[str, Any], ack_date: str | None,
                    invoice_date: str | None, backdating_risk_days: int = 0,
                    covered_fields: tuple[str, ...] = COVERED_FIELDS) -> dict[str, Any]:
    """Verify a signed e-invoice QR envelope and cross-check the covered fields.

    Returns a flat, JSON-serializable result. All states are deterministic.
    """
    official = key_classification == "OFFICIAL_IRP"
    result: dict[str, Any] = {
        "test_id": "T13", "classification": key_classification, "key_id": key_id,
        "signature_valid": False, "externally_verified": False, "government_registered": False,
        "field_mismatches": [], "registration_timing_risk": False, "confirmed_exception": False,
        "ack_date": ack_date, "invoice_date": invoice_date,
    }
    if not envelope_b64:
        return {**result, "state": "UNVERIFIED",
                "reason": "No signed QR payload supplied; nothing to verify cryptographically."}
    if not trusted_public_key_b64:
        return {**result, "state": "UNAVAILABLE",
                "reason": "No trusted verification key is configured; signature verification is unavailable."}
    try:
        envelope = json.loads(base64.b64decode(envelope_b64, validate=True))
        payload = envelope["payload"]
        signature = base64.b64decode(envelope["signature_base64"], validate=True)
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(trusted_public_key_b64, validate=True))
        key.verify(signature, _canonical(payload))  # raises InvalidSignature on tamper/wrong key
    except InvalidSignature:
        return {**result, "state": "INCONSISTENT",
                "reason": "Signed QR signature does not verify against the configured trusted key; possible tampering or wrong key. Human review required."}
    except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError):
        return {**result, "state": "INCONSISTENT",
                "reason": "Signed QR envelope is malformed; human review required."}

    result["signature_valid"] = True
    mismatches = sorted(field for field in covered_fields if payload.get(field) != book_fields.get(field))
    result["field_mismatches"] = mismatches

    ack, inv = _parse_iso(ack_date), _parse_iso(invoice_date)
    if ack and inv and (ack - inv).days > int(backdating_risk_days):
        result["registration_timing_risk"] = True
        result["registration_timing_days"] = (ack - inv).days

    if mismatches:
        return {**result, "state": "INCONSISTENT",
                "reason": "Signature verifies but the signed payload disagrees with the books on: "
                          + ", ".join(mismatches) + ". Human review required."}

    result["externally_verified"] = official
    registered_state = "GOVERNMENT_REGISTERED" if official else "GOVERNMENT_REGISTERED_DEMO"
    result["government_registered"] = official
    timing_note = (" A later acknowledgement date is a backdating-risk indicator to investigate, not proof."
                   if result["registration_timing_risk"] else "")
    scope = ("Signature and covered fields verify against the official trusted key; this supports registration/authenticity of the covered payload only, not physical delivery or transfer of control."
             if official else
             "Signature and covered fields verify against a DEMO key; this demonstrates the verification path only and is NOT government registration.")
    return {**result, "state": registered_state, "reason": scope + timing_note}
