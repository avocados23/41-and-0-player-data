import unittest

from shooting_ability import (
    PlayerShootingInput,
    ZoneCount,
    beta_probability_above,
    build_ability_profiles,
    percent_ranks,
    regularized_beta,
)


def player(
    player_id,
    *,
    season=2026,
    games=30,
    minutes=900,
    rim=(100, 60),
    jumper=(100, 40),
    three=(100, 36),
    free_throw=(80, 60),
    assisted_perimeter_makes=45,
):
    zones = {
        "rim": ZoneCount(*rim),
        "jumper": ZoneCount(*jumper),
        "three_pointer": ZoneCount(*three),
        "free_throw": ZoneCount(*free_throw),
    }
    return PlayerShootingInput(
        player_id=player_id,
        season=season,
        games=games,
        minutes=minutes,
        box_fga=sum(zones[z].attempts for z in ("rim", "jumper", "three_pointer")),
        box_fta=zones["free_throw"].attempts,
        zones=zones,
        perimeter_makes=zones["jumper"].makes + zones["three_pointer"].makes,
        assisted_perimeter_makes=assisted_perimeter_makes,
    )


class BetaMathTests(unittest.TestCase):
    def test_uniform_beta_cdf(self):
        self.assertAlmostEqual(regularized_beta(0.25, 1, 1), 0.25, places=10)
        self.assertAlmostEqual(beta_probability_above(1, 1, 0.25), 0.75, places=10)

    def test_probability_increases_with_makes(self):
        self.assertGreater(
            beta_probability_above(40, 20, 0.5),
            beta_probability_above(20, 40, 0.5),
        )


class AbilityProfileTests(unittest.TestCase):
    def test_percent_ranks_preserve_ties(self):
        self.assertEqual(percent_ranks([1, 2, 2, 3]), [0, 100 / 3, 100 / 3, 100])

    def test_builds_four_zones_and_bounded_scores(self):
        profiles = build_ability_profiles(
            [
                player(1, three=(140, 58), free_throw=(100, 85)),
                player(2, three=(100, 34), free_throw=(80, 58)),
                player(3, three=(40, 10), free_throw=(40, 22)),
            ],
            draws=250,
        )
        self.assertEqual(len(profiles), 3)
        for profile in profiles:
            self.assertEqual({zone["zone"] for zone in profile["zones"]}, {
                "rim", "jumper", "three_pointer", "free_throw"
            })
            for key in (
                "efficiency_score", "spacing_score", "versatility_score",
                "self_creation_score", "confidence_score", "shooting_ability_score",
                "ability_p10", "ability_p50", "ability_p90",
            ):
                self.assertGreaterEqual(profile[key], 0)
                self.assertLessEqual(profile[key], 100)
            self.assertLessEqual(profile["ability_p10"], profile["ability_p50"])
            self.assertLessEqual(profile["ability_p50"], profile["ability_p90"])
            self.assertLessEqual(profile["expected_points_p10"], profile["expected_points_p50"])
            self.assertLessEqual(profile["expected_points_p50"], profile["expected_points_p90"])

    def test_low_volume_accuracy_is_shrunk_more(self):
        profiles = build_ability_profiles(
            [
                player(1, three=(10, 8)),
                player(2, three=(100, 30)),
                player(3, three=(100, 30)),
            ],
            draws=150,
        )
        by_id = {profile["player_id"]: profile for profile in profiles}
        low = next(z for z in by_id[1]["zones"] if z["zone"] == "three_pointer")
        self.assertLess(low["adjusted_accuracy"], 0.8)
        self.assertGreater(low["adjusted_accuracy"], low["league_average"])

    def test_results_are_deterministic(self):
        rows = [player(1), player(2, three=(120, 45))]
        first = build_ability_profiles(rows, draws=200)
        second = build_ability_profiles(rows, draws=200)
        self.assertEqual(first, second)

    def test_seasons_are_normalized_independently(self):
        profiles = build_ability_profiles(
            [player(1, season=2025), player(2, season=2026)],
            draws=100,
        )
        self.assertEqual([p["shooting_ability_score"] for p in profiles], [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
