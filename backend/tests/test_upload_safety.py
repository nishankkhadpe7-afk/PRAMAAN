import base64
import os
import unittest
from unittest.mock import patch

from Pramaan.backend.upload_safety import UploadSafetyError, content_type, decode_base64, max_upload_bytes


class UploadSafetyTests(unittest.TestCase):
    def test_valid_payload_and_content_type_are_normalized(self):
        self.assertEqual(decode_base64(base64.b64encode(b"synthetic").decode(), label="evidence", limit=16), b"synthetic")
        self.assertEqual(content_type("Application/Pdf;Version=1"), "application/pdf;version=1")

    def test_invalid_or_oversized_content_is_refused_before_storage(self):
        with self.assertRaises(UploadSafetyError):
            decode_base64("not base64", label="register", limit=16)
        with self.assertRaises(UploadSafetyError):
            decode_base64(base64.b64encode(b"x" * 17).decode(), label="register", limit=16)
        with self.assertRaises(UploadSafetyError):
            content_type("text/plain\r\nX-Injected: yes")

    def test_limit_is_configurable_and_must_be_positive(self):
        with patch.dict(os.environ, {"PRAMAAN_MAX_UPLOAD_BYTES": "7"}):
            self.assertEqual(max_upload_bytes(), 7)
        with patch.dict(os.environ, {"PRAMAAN_MAX_UPLOAD_BYTES": "0"}):
            with self.assertRaises(RuntimeError):
                max_upload_bytes()


if __name__ == "__main__":
    unittest.main()
