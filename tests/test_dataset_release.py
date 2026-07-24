import tempfile
import unittest
from pathlib import Path

from dataset_release import checksum_files, validate_row_bounds


class DatasetReleaseTests(unittest.TestCase):
    def test_checksum_is_deterministic_and_file_order_sensitive(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.csv"
            second = Path(directory) / "second.csv"
            first.write_text("id\n1\n")
            second.write_text("id\n2\n")
            self.assertEqual(
                checksum_files([first, second]), checksum_files([first, second])
            )
            self.assertNotEqual(
                checksum_files([first, second]), checksum_files([second, first])
            )

    def test_row_bounds_allow_initial_and_reasonable_refreshes(self):
        self.assertEqual(validate_row_bounds("players", 10, 0)["staged"], 10)
        self.assertEqual(validate_row_bounds("players", 90, 100)["staged"], 90)

    def test_row_bounds_reject_empty_or_large_drift(self):
        with self.assertRaisesRegex(ValueError, "no rows"):
            validate_row_bounds("players", 0, 0)
        with self.assertRaisesRegex(ValueError, "row-count bounds"):
            validate_row_bounds("players", 49, 100)


if __name__ == "__main__":
    unittest.main()
