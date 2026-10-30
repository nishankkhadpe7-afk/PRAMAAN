"""Tests for the MCP egress DLP layer and the T13 signed-QR crypto adapter."""
import unittest

from Pramaan.backend import mcp_dlp, p3_crypto


class EgressDlpTests(unittest.TestCase):
    def test_redacts_identifiers_but_preserves_structural_ids(self):
        data = {
            "run_id": "P3-abcdef0123456789",                 # structural id, must survive
            "snapshot_hash": "a" * 64,                         # hex hash, must survive
            "samples": [
                {"object_ref": "INV-001", "buyer_gstin": "29ABCDE1234F1Z5",
                 "contact_email": "ops@aster-demo.example", "phone": "9876543210",
                 "pan": "ABCDE1234F"},
            ],
        }
        filtered, report = mcp_dlp.apply_egress_policy(data, "select_sales_tod")
        self.assertEqual(filtered["run_id"], "P3-abcdef0123456789")
        self.assertEqual(filtered["snapshot_hash"], "a" * 64)
        self.assertEqual(filtered["samples"][0]["object_ref"], "INV-001")
        row = filtered["samples"][0]
        self.assertEqual(row["buyer_gstin"], "[REDACTED:GSTIN]")
        self.assertEqual(row["contact_email"], "[REDACTED:EMAIL]")
        self.assertEqual(row["phone"], "[REDACTED:PHONE]")
        self.assertEqual(row["pan"], "[REDACTED:PAN]")
        self.assertFalse(report["denied"])
        self.assertEqual(report["redaction_counts"]["gstin"], 1)
        self.assertTrue(report["fields_filtered"])
        self.assertGreaterEqual(report["total_redactions"], 4)

    def test_hard_deny_on_financial_account_numbers(self):
        data = {"receipt": {"payer_account": "123456789012345"}}
        with self.assertRaises(mcp_dlp.DeniedByPolicy) as ctx:
            mcp_dlp.apply_egress_policy(data, "get_journal")
        self.assertIn("bank_account", ctx.exception.categories)
        self.assertTrue(ctx.exception.report["denied"])

    def test_clean_payload_passes_through_unchanged(self):
        data = {"run_id": "P3-x", "findings": [{"finding_id": "F3-1", "state": "REVIEW"}]}
        filtered, report = mcp_dlp.apply_egress_policy(data, "get_findings")
        self.assertEqual(filtered, data)
        self.assertEqual(report["total_redactions"], 0)
        self.assertFalse(report["denied"])


class T13AdapterTests(unittest.TestCase):
    BOOK = {"irn": "SYNTH-IRN-003", "bill_no": "PRA/25-26/003", "buyer_gstin": "29ABCDE1234F2Z5",
            "seller_gstin": "29AAAAA0000A1Z5", "gross_cents": 23600000, "hsn_code": "8501", "invoice_date": "2025-04-10"}

    def _env(self, **overrides):
        payload = {**self.BOOK, **overrides}
        return p3_crypto.sign_envelope(payload)

    def test_valid_demo_signature_and_fields_match(self):
        r = p3_crypto.verify_einvoice(self._env(), p3_crypto.DEMO_IRP_PUBLIC_KEY_B64, p3_crypto.DEMO_IRP_KEY_ID,
                                      "DEMO_IRP_TEST_ONLY", self.BOOK, "2025-04-10", "2025-04-10", 0)
        self.assertEqual(r["state"], "GOVERNMENT_REGISTERED_DEMO")
        self.assertTrue(r["signature_valid"])
        self.assertFalse(r["externally_verified"])     # DEMO key never claims official registration
        self.assertFalse(r["government_registered"])
        self.assertEqual(r["field_mismatches"], [])

    def test_tampered_envelope_fails_signature(self):
        env = self._env()
        tampered = ("A" if env[0] != "A" else "B") + env[1:]
        r = p3_crypto.verify_einvoice(tampered, p3_crypto.DEMO_IRP_PUBLIC_KEY_B64, p3_crypto.DEMO_IRP_KEY_ID,
                                      "DEMO_IRP_TEST_ONLY", self.BOOK, "2025-04-10", "2025-04-10", 0)
        self.assertEqual(r["state"], "INCONSISTENT")
        self.assertFalse(r["signature_valid"])

    def test_valid_signature_but_books_disagree(self):
        r = p3_crypto.verify_einvoice(self._env(gross_cents=9999999), p3_crypto.DEMO_IRP_PUBLIC_KEY_B64,
                                      p3_crypto.DEMO_IRP_KEY_ID, "DEMO_IRP_TEST_ONLY", self.BOOK, "2025-04-10", "2025-04-10", 0)
        self.assertEqual(r["state"], "INCONSISTENT")
        self.assertTrue(r["signature_valid"])
        self.assertIn("gross_cents", r["field_mismatches"])

    def test_registration_timing_risk_flag(self):
        r = p3_crypto.verify_einvoice(self._env(), p3_crypto.DEMO_IRP_PUBLIC_KEY_B64, p3_crypto.DEMO_IRP_KEY_ID,
                                      "DEMO_IRP_TEST_ONLY", self.BOOK, "2025-05-01", "2025-04-10", 0)
        self.assertTrue(r["registration_timing_risk"])
        self.assertEqual(r["registration_timing_days"], 21)

    def test_official_key_classification_marks_externally_verified(self):
        r = p3_crypto.verify_einvoice(self._env(), p3_crypto.DEMO_IRP_PUBLIC_KEY_B64, "official-irp-key",
                                      "OFFICIAL_IRP", self.BOOK, "2025-04-10", "2025-04-10", 0)
        self.assertEqual(r["state"], "GOVERNMENT_REGISTERED")
        self.assertTrue(r["externally_verified"])
        self.assertTrue(r["government_registered"])

    def test_missing_payload_and_missing_key(self):
        self.assertEqual(p3_crypto.verify_einvoice("", p3_crypto.DEMO_IRP_PUBLIC_KEY_B64, "k", "DEMO_IRP_TEST_ONLY", self.BOOK, None, None)["state"], "UNVERIFIED")
        self.assertEqual(p3_crypto.verify_einvoice(self._env(), "", "k", "DEMO_IRP_TEST_ONLY", self.BOOK, None, None)["state"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
