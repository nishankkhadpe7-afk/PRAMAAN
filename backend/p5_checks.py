"""Bounded P5 demonstration checks. Never official IRP verification."""
import base64
import json
from decimal import Decimal, InvalidOperation

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def demo_signature(raw, public_key, invoice):
    from . import app as p1
    result = {"test_id": "T13", "state": "UNAVAILABLE", "classification": "DEMO_IRP_TEST_ONLY",
              "government_registered": False, "independently_verified": False,
              "reason": "No trusted Demo IRP public key configured; official verification is unavailable."}
    if not public_key:
        return result
    try:
        envelope = json.loads(raw)
        payload = envelope["payload"]
        if not isinstance(payload, dict) or set(payload) != {"invoice_id", "bill_no", "gross_cents"} or type(payload["gross_cents"]) is not int:
            raise ValueError("invalid demo schema")
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
        key.verify(base64.b64decode(envelope["signature_base64"], validate=True), p1.canonical(payload))
        matches = all(payload[key] == invoice[key] for key in payload)
        return {**result, "state": "DEMO_SIGNATURE_VALID" if matches else "INCONSISTENT",
                "reason": "Demo signature valid; covered book fields match. This is not government registration or delivery evidence." if matches else "Demo signature valid but covered book fields disagree; human review required."}
    except (InvalidSignature, ValueError, KeyError, TypeError, UnicodeError):
        return {**result, "state": "INCONSISTENT", "reason": "Demo signed payload is invalid or its signature fails; human review required."}


def capacity_screen(route):
    result = {"test_id": "T11", "classification": "SYNTHETIC_CAPACITY_SCREEN", "state": "GAP",
              "reason": "Quantity/capacity unavailable or invalid; no impossibility conclusion."}
    try:
        quantity, capacity = Decimal(str(route["quantity_units"])), Decimal(str(route["vehicle_capacity_units"]))
        if not quantity.is_finite() or not capacity.is_finite() or quantity < 0 or capacity <= 0:
            return result
        return {**result, "state": "REVIEW" if quantity > capacity else "SCREEN_CLEAR",
                "reason": "Synthetic quantity exceeds stated capacity; sources are unverified, so this is review-only." if quantity > capacity else "No capacity conflict in the supplied unverified values; this does not substantiate movement."}
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return result
