"""Guards the synthetic evaluation: detectors must beat the document-matching
baseline and raise no hard-conflict false alarms on innocent cases."""
import unittest

from Pramaan.backend import evaluate


class EvaluationTests(unittest.TestCase):
    def test_measured_detection_beats_baseline_with_no_hard_false_alarms(self):
        r = evaluate.run_evaluation()
        # Every planted irregularity is surfaced.
        self.assertEqual(r["pramaan_caught_A"], r["planted_total_X"])
        self.assertTrue(all(c["caught"] for c in r["per_class"]))
        # Pramaan strictly beats the invoice-vs-dispatch baseline.
        self.assertGreater(r["pramaan_caught_A"], r["baseline_doc_match_caught_B"])
        # No hard conflict is raised against an innocent sale.
        self.assertEqual(r["false_alarms_on_innocent_C"], 0)
        # The baseline must miss at least the physics/provenance/registration-only cases.
        missed_by_baseline = [c for c in r["per_class"] if c["caught"] and not c["baseline_caught"]]
        self.assertTrue(missed_by_baseline)


if __name__ == "__main__":
    unittest.main()
