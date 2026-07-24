import os
import unittest
from pathlib import Path
from unittest.mock import patch

from import_audit import pipeline_commit


class PipelineCommitTests(unittest.TestCase):
    def test_uses_valid_configured_commit(self):
        with patch.dict(os.environ, {"PIPELINE_COMMIT": "ABCDEF1234567"}):
            self.assertEqual(pipeline_commit(Path(".")), "abcdef1234567")

    def test_rejects_non_hex_commit(self):
        with patch.dict(os.environ, {"PIPELINE_COMMIT": "not-a-commit"}):
            with self.assertRaisesRegex(ValueError, "hexadecimal"):
                pipeline_commit(Path("."))


if __name__ == "__main__":
    unittest.main()
