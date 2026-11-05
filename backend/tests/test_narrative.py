"""Tests for the AI narrative citation validator (offline; LLM poster mocked)."""
import asyncio
import unittest

from Pramaan.backend import narrative


class NarrativeValidatorTests(unittest.TestCase):
    def test_drops_uncited_and_hallucinated_sentences(self):
        text = ("The invoice and dispatch disagree on taxable value [F3-abc]. "
                "This is definitely fraud. "
                "The transporter confirmed delivery [F3-ghost].")
        result = narrative.validate_narrative(text, {"F3-abc"})
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["citations"], ["F3-abc"])
        reasons = " ".join(r["reason"] for r in result["rejected"])
        self.assertIn("no evidence citation", reasons)      # "definitely fraud" dropped
        self.assertIn("unresolved citation", reasons)        # ghost id dropped
        self.assertFalse(result["all_valid"])

    def test_all_cited_sentences_pass(self):
        result = narrative.validate_narrative("Invoice and dispatch values differ [F3-abc].", {"F3-abc"})
        self.assertTrue(result["all_valid"])
        self.assertEqual(result["validated_text"], "Invoice and dispatch values differ [F3-abc].")

    def test_valid_ids_for_collects_finding_identifiers(self):
        finding = {"finding_id": "F3-1", "object_ref": "INV-009", "evidence_ids": ["EV-1"], "invoice_ids": ["INV-004", "INV-009"]}
        ids = narrative.valid_ids_for(finding)
        self.assertEqual(ids, {"F3-1", "INV-009", "EV-1", "INV-004"})

    def test_draft_keeps_only_validated_sentences(self):
        finding = {"finding_id": "F3-1", "object_ref": "INV-009", "reason": "Signed fields disagree with the books"}

        async def good_poster(cfg, body):
            return {"choices": [{"message": {"content": "The signed e-invoice fields disagree with the books [F3-1]. The vendor is clearly a shell company."}}]}

        result = asyncio.run(narrative.draft_narrative(finding, {"F3-1", "INV-009"}, {"model": "qwen/qwen3.8-27b"}, good_poster))
        self.assertEqual(len(result["accepted"]), 1)          # second (uncited) sentence dropped
        self.assertIn("[F3-1]", result["validated_text"])
        self.assertFalse(result.get("used_fallback"))

    def test_fallback_when_model_cites_nothing(self):
        finding = {"finding_id": "F3-9", "object_ref": "INV-007", "reason": "Implied road speed exceeds the hard maximum"}

        async def bad_poster(cfg, body):
            return {"choices": [{"message": {"content": "This sale is fake."}}]}

        result = asyncio.run(narrative.draft_narrative(finding, {"F3-9", "INV-007"}, {"model": "m"}, bad_poster))
        self.assertTrue(result["used_fallback"])
        self.assertTrue(result["accepted"])                   # deterministic cited fallback survives
        self.assertIn("[F3-9]", result["validated_text"])


if __name__ == "__main__":
    unittest.main()
