import unittest

from bracketballer_data.contextual_shooting import (
    BaseProfile,
    GameContext,
    ZoneContext,
    build_contextual_profiles,
)


def zone(attempts, makes, *, clutch_attempts=0, clutch_makes=0, league=.4, player=.4, per40=4, threat=.6):
    return ZoneContext(
        attempts, makes, clutch_attempts, clutch_makes,
        league, player, per40, threat,
    )


def game(player_id, game_id, *, three_makes, clutch_three_makes, postseason=False):
    return GameContext(
        player_id=player_id,
        season=2026,
        game_id=game_id,
        opponent_id=100 + game_id,
        opponent=f"Opponent {game_id}",
        game_start_date=None,
        season_type="postseason" if postseason else "regular",
        tournament="NCAA" if postseason else None,
        zones={
            "rim": zone(4, 3, league=.6, player=.62, per40=4, threat=.8),
            "jumper": zone(3, 1, league=.4, player=.4, per40=3, threat=.6),
            "three_pointer": zone(
                6, three_makes,
                clutch_attempts=2,
                clutch_makes=clutch_three_makes,
                league=.35,
                player=.4,
                per40=7,
                threat=.9,
            ),
            "free_throw": zone(4, 3, clutch_attempts=2, clutch_makes=2, league=.75, player=.8),
        },
        assisted_perimeter_makes=1,
        perimeter_makes=1 + three_makes,
    )


def base(player_id, *, ability=85, spacing=92, creation=85):
    return BaseProfile(
        player_id=player_id,
        season=2026,
        games=25,
        minutes=800,
        event_coverage=1.0,
        efficiency_score=80,
        shot_making_score=80,
        spacing_score=spacing,
        versatility_score=85,
        self_creation_score=creation,
        free_throw_score=95,
        confidence_score=80,
        shooting_ability_score=ability,
    )


class ContextualSignalTests(unittest.TestCase):
    def test_builds_game_rows_context_scores_and_labels(self):
        games = []
        for game_id in range(1, 7):
            games.append(game(1, game_id, three_makes=3, clutch_three_makes=2, postseason=game_id >= 5))
            games.append(game(2, game_id + 20, three_makes=1 if game_id % 2 else 4, clutch_three_makes=0, postseason=game_id >= 5))
        bases = {(1, 2026): base(1), (2, 2026): base(2, ability=45, spacing=60, creation=40)}

        game_rows, profiles = build_contextual_profiles(
            games, bases, model_version="shooting-v1", draws=100
        )
        self.assertEqual(len(game_rows), 12)
        by_id = {profile["player_id"]: profile for profile in profiles}
        self.assertGreater(by_id[1]["clutch_score"], by_id[2]["clutch_score"])
        self.assertGreater(by_id[1]["clutch_points_above_expected"], 0)
        self.assertLessEqual(by_id[1]["clutch_delta_p10"], by_id[1]["clutch_delta_p90"])
        self.assertIn("ELITE_SPACER", by_id[1]["role_labels"])
        self.assertIn("HIGH_VOLUME_SHOOTER", by_id[1]["role_labels"])
        self.assertIn("THREE_LEVEL_SCORER", by_id[1]["role_labels"])
        self.assertIn("SELF_CREATING_SHOOTER", by_id[1]["role_labels"])

    def test_results_are_deterministic(self):
        games = [game(1, index, three_makes=3, clutch_three_makes=1) for index in range(1, 5)]
        bases = {(1, 2026): base(1)}
        first = build_contextual_profiles(games, bases, model_version="shooting-v1", draws=100)
        second = build_contextual_profiles(games, bases, model_version="shooting-v1", draws=100)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
