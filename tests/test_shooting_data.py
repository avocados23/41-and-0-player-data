import unittest

from bracketballer_data.shooting_data import (
    ACCURACY_PRIOR_ATTEMPTS,
    ShootingAggregate,
    build_shooting_profiles,
    event_record,
    normalize_eligible_plays,
    normalize_play,
)


def aggregate(
    player_id,
    *,
    season=2026,
    games=20,
    events=200,
    field_goals=150,
    free_throws=50,
    three_attempts=60,
    three_made=21,
    assisted_threes=None,
    coordinates=120,
):
    return ShootingAggregate(
        player_id,
        season,
        games,
        events,
        field_goals,
        free_throws,
        three_attempts,
        three_made,
        min(three_made, 15) if assisted_threes is None else assisted_threes,
        coordinates,
    )


class NormalizePlayTests(unittest.TestCase):
    def test_flattens_alias_keyed_shot(self):
        raw = {
            "id": 38032603,
            "sourceId": "401810001",
            "gameId": 212822,
            "gameSourceId": "401810001",
            "gameStartDate": "2025-11-05T00:30:00Z",
            "season": 2026,
            "seasonType": "regular",
            "playType": "JumpShot",
            "teamId": 2724,
            "team": "Wichita State",
            "opponentId": 2000,
            "opponent": "Opponent",
            "period": 1,
            "clock": "18:44",
            "secondsRemaining": 1124,
            "playText": "Kenyon Giles made Three Point Jumper.",
            "shotInfo": {
                "shooter": {"name": "Kenyon Giles", "id": 2246},
                "made": True,
                "range": "three_pointer",
                "assisted": True,
                "assistedBy": {"name": "Teammate", "id": 999},
                "location": {"x": 705, "y": 420},
            },
        }

        result = normalize_play(raw, 2246, 2026)

        self.assertEqual(result["source_play_id"], 38032603)
        self.assertEqual(result["player_id"], 2246)
        self.assertEqual(result["shot_range"], "three_pointer")
        self.assertEqual(result["assisted_by_player_id"], 999)
        self.assertEqual(result["location_x"], 705)
        self.assertIsNotNone(result["raw_payload"])
        self.assertEqual(len(event_record(result)), 25)

    def test_retains_free_throw_without_coordinates(self):
        raw = {
            "id": 7,
            "sourceId": "7",
            "gameId": 11,
            "season": 2020,
            "shotInfo": {
                "shooter": {"name": "Player", "id": 42},
                "made": False,
                "range": "free_throw",
                "assisted": False,
                "assistedBy": {"name": None, "id": None},
                "location": {"x": None, "y": None},
            },
        }

        result = normalize_play(raw, 42, 2020)

        self.assertEqual(result["shot_range"], "free_throw")
        self.assertIsNone(result["location_x"])
        self.assertIsNone(result["location_y"])

    def test_rejects_conflicting_shooter(self):
        raw = {
            "id": 7,
            "gameId": 11,
            "shotInfo": {"shooter": {"id": 99}},
        }
        with self.assertRaisesRegex(ValueError, "does not match"):
            normalize_play(raw, 42, 2020)

    def test_bulk_filter_keeps_only_database_players_in_requested_season(self):
        def play(play_id, player_id, season):
            return {
                "id": play_id,
                "gameId": 11,
                "season": season,
                "shotInfo": {
                    "shooter": {"id": player_id, "name": str(player_id)},
                    "made": True,
                    "range": "three_pointer",
                    "assisted": False,
                    "assistedBy": {"id": None, "name": None},
                    "location": {"x": 1, "y": 2},
                },
            }

        results = normalize_eligible_plays(
            [
                play(1, 42, 2026),
                play(2, 99, 2026),
                play(3, 42, 2025),
                play(1, 42, 2026),
            ],
            {42},
            2026,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["player_id"], 42)
        self.assertEqual(results[0]["source_play_id"], 1)


class ShooterProfileTests(unittest.TestCase):
    def test_balanced_score_labels_only_high_sample_elite_profile(self):
        rows = [
            aggregate(
                1,
                three_attempts=120,
                three_made=48,
                field_goals=220,
                assisted_threes=35,
            ),
            aggregate(
                2,
                three_attempts=70,
                three_made=24,
                field_goals=180,
                assisted_threes=15,
            ),
            aggregate(
                3,
                three_attempts=20,
                three_made=6,
                field_goals=140,
                assisted_threes=3,
            ),
        ]

        profiles = {p["player_id"]: p for p in build_shooting_profiles(rows)}

        self.assertEqual(profiles[1]["shooter_score"], 100)
        self.assertTrue(profiles[1]["is_shooter"])
        self.assertFalse(profiles[2]["is_shooter"])
        self.assertFalse(profiles[3]["is_shooter"])
        self.assertAlmostEqual(profiles[1]["assisted_three_rate"], 35 / 48)
        self.assertAlmostEqual(profiles[1]["coordinate_coverage"], 120 / 220)

    def test_accuracy_is_shrunk_toward_season_mean(self):
        rows = [
            aggregate(1, three_attempts=10, three_made=8),
            aggregate(2, three_attempts=90, three_made=27),
        ]
        profiles = {p["player_id"]: p for p in build_shooting_profiles(rows)}
        season_mean = 35 / 100
        expected = (8 + season_mean * ACCURACY_PRIOR_ATTEMPTS) / (
            10 + ACCURACY_PRIOR_ATTEMPTS
        )
        self.assertAlmostEqual(profiles[1]["adjusted_three_point_pct"], expected)
        self.assertLess(
            profiles[1]["adjusted_three_point_pct"],
            profiles[1]["raw_three_point_pct"],
        )

    def test_minimum_attempts_blocks_label_even_with_top_score(self):
        rows = [
            aggregate(1, three_attempts=49, three_made=25, field_goals=70),
            aggregate(2, three_attempts=10, three_made=1, field_goals=100),
        ]
        profiles = {p["player_id"]: p for p in build_shooting_profiles(rows)}
        self.assertEqual(profiles[1]["shooter_score"], 100)
        self.assertFalse(profiles[1]["is_shooter"])

    def test_seasons_are_ranked_independently(self):
        profiles = build_shooting_profiles(
            [
                aggregate(1, season=2025, three_attempts=80, three_made=30),
                aggregate(2, season=2026, three_attempts=80, three_made=30),
            ]
        )
        self.assertEqual([profile["shooter_score"] for profile in profiles], [0, 0])


if __name__ == "__main__":
    unittest.main()
