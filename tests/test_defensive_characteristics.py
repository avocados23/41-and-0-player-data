import unittest

from defensive_characteristics import (
    PlayerDefensiveEvidence,
    score_characteristics,
)


def evidence(player_id: int, **overrides):
    values = {
        "player_id": player_id,
        "team_id": 1,
        "season": 2026,
        "games": 20,
        "season_games": 20,
        "possessions": 600,
        "center_role_share": 0.9,
        "height": 82,
        "block_pct": 5,
        "steal_pct": 2,
        "defensive_rebound_pct": 22,
        "dporpag": 3,
        "dbpm": 4,
        "fouls_per40": 3,
        "interior_attempt_rate_delta": -0.08,
        "interior_accuracy_delta": -0.06,
        "jumper_attempt_rate_delta": 0.07,
        "opponent_offensive_rebound_pct_delta": -0.04,
        "opponent_turnover_rate_delta": 0.02,
        "opponent_free_throw_rate_delta": -0.02,
        "adjusted_defense_rating_delta": -8,
        "finalized_game_coverage": 1,
        "lineup_coverage": 1,
        "data_through_date": "2026-02-01",
    }
    values.update(overrides)
    return PlayerDefensiveEvidence(**values)


class DefensiveCharacteristicTests(unittest.TestCase):
    def test_strong_interior_results_beat_blocks_only(self):
        strong = evidence(1)
        blocks_only = evidence(
            2,
            block_pct=8,
            interior_attempt_rate_delta=0.08,
            interior_accuracy_delta=0.10,
            jumper_attempt_rate_delta=-0.06,
            adjusted_defense_rating_delta=6,
        )
        scores = score_characteristics([strong, blocks_only], scheme_validated=True)
        by_player_key = {(row.player_id, row.key): row for row in scores}
        self.assertGreater(
            by_player_key[(1, "RIM_PROTECTOR")].score,
            by_player_key[(2, "RIM_PROTECTOR")].score,
        )
        self.assertGreater(
            by_player_key[(1, "LIKELY_DROP_ANCHOR")].score,
            by_player_key[(2, "LIKELY_DROP_ANCHOR")].score,
        )

    def test_scheme_label_requires_sample_confidence_and_validation(self):
        rows = [evidence(1), evidence(2, possessions=50)]
        unvalidated = score_characteristics(rows, scheme_validated=False)
        self.assertFalse(
            next(
                row
                for row in unvalidated
                if row.player_id == 1 and row.key == "LIKELY_DROP_ANCHOR"
            ).qualified
        )
        validated = score_characteristics(rows, scheme_validated=True)
        small = next(
            row
            for row in validated
            if row.player_id == 2 and row.key == "LIKELY_DROP_ANCHOR"
        )
        self.assertFalse(small.qualified)
        self.assertIn("SMALL_LINEUP_SAMPLE", small.limitations)

    def test_scores_are_bounded(self):
        scores = score_characteristics([evidence(1), evidence(2)])
        self.assertTrue(all(0 <= row.score <= 100 for row in scores))
        self.assertTrue(all(0 <= row.confidence <= 100 for row in scores))

    def test_small_samples_are_shrunk_toward_population_average(self):
        large = evidence(1, possessions=1000)
        small = evidence(2, possessions=25)
        weak = evidence(
            3,
            possessions=1000,
            block_pct=0,
            defensive_rebound_pct=5,
            dporpag=-2,
            dbpm=-4,
            interior_attempt_rate_delta=0.10,
            interior_accuracy_delta=0.10,
        )
        by_player = {
            row.player_id: row
            for row in score_characteristics([large, small, weak])
            if row.key == "RIM_PROTECTOR"
        }
        self.assertGreater(by_player[1].score, by_player[2].score)
        self.assertLess(abs(by_player[2].score - 50), abs(by_player[1].score - 50))

    def test_percentiles_are_computed_within_each_season(self):
        first_season = [
            evidence(1, season=2025, block_pct=8),
            evidence(2, season=2025, block_pct=1),
        ]
        second_season = [
            evidence(3, season=2026, block_pct=80),
            evidence(4, season=2026, block_pct=10),
        ]
        scores = score_characteristics(first_season + second_season)
        by_player = {
            row.player_id: row.score
            for row in scores
            if row.key == "RIM_PROTECTOR"
        }
        self.assertEqual(by_player[1], by_player[3])
        self.assertEqual(by_player[2], by_player[4])

    def test_missing_coverage_reduces_confidence(self):
        complete = evidence(1)
        incomplete = evidence(
            2,
            finalized_game_coverage=0.5,
            lineup_coverage=0.5,
        )
        scores = score_characteristics([complete, incomplete])
        confidence = {
            row.player_id: row.confidence
            for row in scores
            if row.key == "RIM_PROTECTOR"
        }
        self.assertGreater(confidence[1], confidence[2])


if __name__ == "__main__":
    unittest.main()
