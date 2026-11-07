import unittest

from Pramaan.backend import release_verify


class ReleaseEvidenceTests(unittest.TestCase):
    def test_manifest_captures_inputs_evaluation_and_limits(self):
        manifest = release_verify.build_manifest(created_at="2026-10-31T00:00:00+00:00")
        self.assertEqual(manifest["schema_version"], "pramaan-release-evidence-v1")
        self.assertEqual(manifest["evaluation"]["pramaan_caught_A"], manifest["evaluation"]["planted_total_X"])
        self.assertEqual(len(manifest["dataset_manifest_sha256"]), 64)
        self.assertEqual(len(manifest["manifest_sha256"]), 64)
        self.assertIn("p3.py", manifest["implementation_sha256"])
        self.assertTrue(any("Synthetic" in limit for limit in manifest["limitations"]))
        release_verify.require_quality(manifest)


if __name__ == "__main__":
    unittest.main()
