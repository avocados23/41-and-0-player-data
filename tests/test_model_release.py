import unittest

from model_release import validate_release_counts


class ModelReleaseValidationTests(unittest.TestCase):
    def test_accepts_complete_candidate(self):
        validate_release_counts(
            {
                "ability_profiles": 3,
                "zone_profiles": 12,
                "game_profiles": 18,
                "contextual_profiles": 3,
            }
        )

    def test_rejects_missing_profiles(self):
        incomplete = (
            {
                "ability_profiles": 0,
                "zone_profiles": 0,
                "game_profiles": 0,
                "contextual_profiles": 0,
            },
            {
                "ability_profiles": 3,
                "zone_profiles": 11,
                "game_profiles": 18,
                "contextual_profiles": 3,
            },
            {
                "ability_profiles": 3,
                "zone_profiles": 12,
                "game_profiles": 18,
                "contextual_profiles": 2,
            },
            {
                "ability_profiles": 3,
                "zone_profiles": 12,
                "game_profiles": 2,
                "contextual_profiles": 3,
            },
        )
        for counts in incomplete:
            with self.subTest(counts=counts):
                with self.assertRaisesRegex(ValueError, "incomplete|no ability"):
                    validate_release_counts(counts)


if __name__ == "__main__":
    unittest.main()
