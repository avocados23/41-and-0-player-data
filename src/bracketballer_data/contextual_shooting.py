"""Pure contextual shooting-signal calculations built on shooting-v1."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

import numpy as np


FIELD_ZONES = ("rim", "jumper", "three_pointer")
ALL_ZONES = (*FIELD_ZONES, "free_throw")
POINT_VALUES = {"rim": 2.0, "jumper": 2.0, "three_pointer": 3.0, "free_throw": 1.0}
CONTEXT_PRIOR_ATTEMPTS = 20.0
CLUTCH_DRAWS = 2_000


@dataclass(frozen=True)
class ZoneContext:
    attempts: int
    makes: int
    clutch_attempts: int
    clutch_makes: int
    league_accuracy: float
    player_accuracy: float
    attempts_per40: float
    threat_score: float


@dataclass(frozen=True)
class GameContext:
    player_id: int
    season: int
    game_id: int
    opponent_id: int | None
    opponent: str | None
    game_start_date: object
    season_type: str | None
    tournament: str | None
    zones: Mapping[str, ZoneContext]
    assisted_perimeter_makes: int
    perimeter_makes: int


@dataclass(frozen=True)
class BaseProfile:
    player_id: int
    season: int
    games: int
    minutes: int
    event_coverage: float
    efficiency_score: float
    shot_making_score: float
    spacing_score: float
    versatility_score: float
    self_creation_score: float
    free_throw_score: float
    confidence_score: float
    shooting_ability_score: float


def _percentiles(values: list[float], reference: list[float]) -> list[float]:
    if not reference:
        return [50.0] * len(values)
    ordered = np.sort(np.asarray(reference, dtype=float))
    denominator = max(1, len(ordered) - 1)
    return [
        100.0
        * min(len(ordered) - 1, int(np.searchsorted(ordered, value, side="left")))
        / denominator
        for value in values
    ]


def _quantile(values: list[float], probability: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=float), probability)) if values else 0.0


def _seed(player_id: int, season: int, version: str) -> int:
    digest = hashlib.sha256(f"context:{version}:{season}:{player_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _zone(game: GameContext, name: str) -> ZoneContext:
    return game.zones.get(name, ZoneContext(0, 0, 0, 0, 0.5, 0.5, 0.0, 0.0))


def _game_values(game: GameContext) -> dict:
    fga = sum(_zone(game, zone).attempts for zone in FIELD_ZONES)
    fgm = sum(_zone(game, zone).makes for zone in FIELD_ZONES)
    three = _zone(game, "three_pointer")
    free_throw = _zone(game, "free_throw")
    points = sum(_zone(game, zone).makes * POINT_VALUES[zone] for zone in ALL_ZONES)
    possessions = fga + 0.44 * free_throw.attempts
    league_expected = sum(
        _zone(game, zone).attempts * POINT_VALUES[zone] * _zone(game, zone).league_accuracy
        for zone in ALL_ZONES
    )
    player_expected = sum(
        _zone(game, zone).attempts * POINT_VALUES[zone] * _zone(game, zone).player_accuracy
        for zone in ALL_ZONES
    )
    clutch_fga = sum(_zone(game, zone).clutch_attempts for zone in FIELD_ZONES)
    clutch_points = sum(
        _zone(game, zone).clutch_makes * POINT_VALUES[zone] for zone in ALL_ZONES
    )
    clutch_expected = sum(
        _zone(game, zone).clutch_attempts
        * POINT_VALUES[zone]
        * _zone(game, zone).player_accuracy
        for zone in ALL_ZONES
    )
    return {
        "player_id": game.player_id,
        "season": game.season,
        "game_id": game.game_id,
        "game_start_date": game.game_start_date,
        "opponent_id": game.opponent_id,
        "opponent": game.opponent,
        "season_type": game.season_type,
        "tournament": game.tournament,
        "field_goal_attempts": fga,
        "field_goals_made": fgm,
        "three_point_attempts": three.attempts,
        "three_points_made": three.makes,
        "free_throw_attempts": free_throw.attempts,
        "free_throws_made": free_throw.makes,
        "rim_attempts": _zone(game, "rim").attempts,
        "jumper_attempts": _zone(game, "jumper").attempts,
        "points": int(points),
        "shooting_possessions": possessions,
        "expected_league_points": league_expected,
        "expected_player_points": player_expected,
        "execution_above_expected": (
            100.0 * (points - player_expected) / possessions if possessions else 0.0
        ),
        "late_close_fga": clutch_fga,
        "late_close_three_pa": three.clutch_attempts,
        "late_close_fta": free_throw.clutch_attempts,
        "late_close_points": int(clutch_points),
        "late_close_expected_points": clutch_expected,
        "assisted_perimeter_makes": game.assisted_perimeter_makes,
        "perimeter_makes": game.perimeter_makes,
    }


def _clutch_interval(
    player_games: list[GameContext],
    player_id: int,
    season: int,
    version: str,
    draws: int,
) -> tuple[float | None, float | None]:
    attempts = {
        zone: sum(_zone(game, zone).clutch_attempts for game in player_games)
        for zone in ALL_ZONES
    }
    if sum(attempts.values()) == 0:
        return None, None
    makes = {
        zone: sum(_zone(game, zone).clutch_makes for game in player_games)
        for zone in ALL_ZONES
    }
    baseline = {
        zone: next(
            (_zone(game, zone).player_accuracy for game in player_games if zone in game.zones),
            0.5,
        )
        for zone in ALL_ZONES
    }
    fga = sum(attempts[zone] for zone in FIELD_ZONES)
    denominator = fga + 0.44 * attempts["free_throw"]
    if denominator == 0:
        return None, None
    expected = sum(
        attempts[zone] * POINT_VALUES[zone] * baseline[zone] for zone in ALL_ZONES
    )
    rng = np.random.default_rng(_seed(player_id, season, version))
    sampled_points = np.zeros(draws)
    for zone in ALL_ZONES:
        alpha = makes[zone] + CONTEXT_PRIOR_ATTEMPTS * baseline[zone]
        beta = attempts[zone] - makes[zone] + CONTEXT_PRIOR_ATTEMPTS * (1 - baseline[zone])
        sampled_points += (
            attempts[zone] * POINT_VALUES[zone] * rng.beta(alpha, beta, draws)
        )
    deltas = 100.0 * (sampled_points - expected) / denominator
    bounds = np.quantile(deltas, [0.1, 0.9])
    return float(bounds[0]), float(bounds[1])


def build_contextual_profiles(
    games: list[GameContext],
    bases: Mapping[tuple[int, int], BaseProfile],
    *,
    model_version: str,
    draws: int = CLUTCH_DRAWS,
) -> tuple[list[dict], list[dict]]:
    game_rows = [_game_values(game) for game in games]
    games_by_player: dict[tuple[int, int], list[tuple[GameContext, dict]]] = {}
    for game, values in zip(games, game_rows):
        games_by_player.setdefault((game.player_id, game.season), []).append((game, values))

    # A negative opponent residual means opponents shoot worse than expected.
    opponent_totals: dict[tuple[int, int], list[float]] = {}
    for values in game_rows:
        if values["opponent_id"] is None:
            continue
        key = (values["season"], values["opponent_id"])
        total = opponent_totals.setdefault(key, [0.0, 0.0])
        total[0] += values["points"] - values["expected_league_points"]
        total[1] += values["shooting_possessions"]
    opponent_difficulty = {
        key: (-100.0 * residual / possessions) * (possessions / (possessions + 200.0))
        for key, (residual, possessions) in opponent_totals.items()
        if possessions > 0
    }
    difficulty_thresholds = {
        season: _quantile(
            [value for (candidate_season, _), value in opponent_difficulty.items() if candidate_season == season],
            0.75,
        )
        for season in {season for season, _ in opponent_difficulty}
    }

    raw_profiles: list[dict] = []
    for key, pairs in sorted(games_by_player.items()):
        base = bases.get(key)
        if base is None:
            continue
        player_games = [pair[0] for pair in pairs]
        values = [pair[1] for pair in pairs]
        total_fga = sum(row["field_goal_attempts"] for row in values)
        total_fta = sum(row["free_throw_attempts"] for row in values)
        total_rim = sum(row["rim_attempts"] for row in values)
        selection_points = sum(
            _zone(game, zone).attempts
            * POINT_VALUES[zone]
            * _zone(game, zone).league_accuracy
            for game in player_games
            for zone in FIELD_ZONES
        )
        execution_games = [
            row["execution_above_expected"]
            for row in values
            if row["shooting_possessions"] >= 5
        ]
        median_execution = float(np.median(execution_games)) if execution_games else 0.0
        mad = (
            float(np.median(np.abs(np.asarray(execution_games) - median_execution)))
            if execution_games else 0.0
        )

        clutch_fga = sum(row["late_close_fga"] for row in values)
        clutch_three_pa = sum(row["late_close_three_pa"] for row in values)
        clutch_fta = sum(row["late_close_fta"] for row in values)
        clutch_points = sum(row["late_close_points"] for row in values)
        clutch_expected = sum(row["late_close_expected_points"] for row in values)
        clutch_possessions = clutch_fga + 0.44 * clutch_fta
        clutch_fgm = sum(
            _zone(game, zone).clutch_makes for game in player_games for zone in FIELD_ZONES
        )
        clutch_three_pm = sum(_zone(game, "three_pointer").clutch_makes for game in player_games)
        clutch_delta = (
            100.0 * (clutch_points - clutch_expected) / clutch_possessions
            if clutch_possessions else None
        )
        clutch_reliability = clutch_possessions / (clutch_possessions + 20.0)
        p10, p90 = _clutch_interval(
            player_games, base.player_id, base.season, model_version, draws
        )

        postseason = [row for row in values if row["season_type"] == "postseason"]
        postseason_possessions = sum(row["shooting_possessions"] for row in postseason)
        postseason_delta = (
            100.0
            * sum(row["points"] - row["expected_player_points"] for row in postseason)
            / postseason_possessions
            if postseason_possessions else None
        )
        postseason_reliability = postseason_possessions / (postseason_possessions + 30.0)

        threshold = difficulty_thresholds.get(base.season, float("inf"))
        strong = [
            row for row in values
            if row["opponent_id"] is not None
            and opponent_difficulty.get((base.season, row["opponent_id"]), float("-inf")) >= threshold
        ]
        strong_possessions = sum(row["shooting_possessions"] for row in strong)
        matchup_delta = (
            100.0
            * sum(row["points"] - row["expected_player_points"] for row in strong)
            / strong_possessions
            if strong_possessions else None
        )
        matchup_reliability = strong_possessions / (strong_possessions + 30.0)

        perimeter_makes = sum(row["perimeter_makes"] for row in values)
        assisted_makes = sum(row["assisted_perimeter_makes"] for row in values)
        raw_profiles.append({
            "player_id": base.player_id,
            "season": base.season,
            "base": base,
            "player_games": player_games,
            "clutch_games": sum(1 for row in values if row["late_close_fga"] + row["late_close_fta"] > 0),
            "clutch_fga": clutch_fga,
            "clutch_three_pa": clutch_three_pa,
            "clutch_fta": clutch_fta,
            "clutch_points": clutch_points,
            "clutch_efg_pct": (
                100.0 * (clutch_fgm + 0.5 * clutch_three_pm) / clutch_fga
                if clutch_fga else None
            ),
            "clutch_true_shooting_pct": (
                100.0 * clutch_points / (2.0 * clutch_possessions)
                if clutch_possessions else None
            ),
            "clutch_points_above_expected": clutch_delta,
            "clutch_raw": (clutch_delta or 0.0) * clutch_reliability,
            "clutch_confidence": 100.0 * clutch_reliability * base.event_coverage,
            "clutch_delta_p10": p10,
            "clutch_delta_p90": p90,
            "median_game_execution": median_execution,
            "execution_mad": mad,
            "shooting_floor": _quantile(execution_games, 0.2),
            "shooting_ceiling": _quantile(execution_games, 0.8),
            "above_expectation_game_rate": (
                sum(value > 0 for value in execution_games) / len(execution_games)
                if execution_games else 0.0
            ),
            "consistency_raw": -mad,
            "selection_value_per_100_fga": (
                100.0 * selection_points / total_fga if total_fga else 0.0
            ),
            "rim_pressure_per40": (
                40.0 * (total_rim + 0.44 * total_fta) / base.minutes
            ),
            "assisted_perimeter_make_rate": (
                assisted_makes / perimeter_makes if perimeter_makes else None
            ),
            "postseason_possessions": postseason_possessions,
            "postseason_points_above_expected": postseason_delta,
            "postseason_raw": (postseason_delta or 0.0) * postseason_reliability,
            "postseason_confidence": 100.0 * postseason_reliability * base.event_coverage,
            "strong_opponent_possessions": strong_possessions,
            "matchup_points_above_expected": matchup_delta,
            "matchup_raw": (matchup_delta or 0.0) * matchup_reliability,
            "matchup_confidence": 100.0 * matchup_reliability * base.event_coverage,
        })

    # Every contextual score is relative to a same-season, >18-game reference.
    score_inputs = {
        "clutch_score": "clutch_raw",
        "consistency_score": "consistency_raw",
        "selection_score": "selection_value_per_100_fga",
        "rim_pressure_score": "rim_pressure_per40",
        "postseason_score": "postseason_raw",
        "matchup_resistance_score": "matchup_raw",
        "assisted_rate_score": "assisted_perimeter_make_rate",
    }
    for score_name, raw_name in score_inputs.items():
        by_season: dict[int, list[int]] = {}
        for index, profile in enumerate(raw_profiles):
            value = profile[raw_name]
            eligible = value is not None
            if score_name == "postseason_score":
                eligible = eligible and profile["postseason_possessions"] > 0
            if score_name == "matchup_resistance_score":
                eligible = eligible and profile["strong_opponent_possessions"] > 0
            if score_name == "clutch_score":
                eligible = eligible and profile["clutch_fga"] + profile["clutch_fta"] > 0
            if eligible:
                by_season.setdefault(profile["season"], []).append(index)
        for indices in by_season.values():
            reference_indices = [
                index for index in indices if raw_profiles[index]["base"].games > 18
            ] or indices
            values = [float(raw_profiles[index][raw_name]) for index in indices]
            reference = [float(raw_profiles[index][raw_name]) for index in reference_indices]
            scores = _percentiles(values, reference)
            for index, score in zip(indices, scores):
                raw_profiles[index][score_name] = score

    contextual_rows: list[dict] = []
    for profile in raw_profiles:
        base: BaseProfile = profile["base"]
        assisted_score = profile.get("assisted_rate_score", 0.0)
        scalability = (
            0.40 * base.spacing_score
            + 0.20 * base.efficiency_score
            + 0.20 * assisted_score
            + 0.10 * base.versatility_score
            + 0.10 * base.confidence_score
        )
        volatility = 100.0 - profile["consistency_score"]
        zones = {
            zone: next(
                (_zone(game, zone) for game in profile["player_games"] if zone in game.zones),
                _zone(profile["player_games"][0], zone),
            )
            for zone in ALL_ZONES
        }
        three_per40 = zones["three_pointer"].attempts_per40
        jumper_attempts = sum(_zone(game, "jumper").attempts for game in profile["player_games"])
        total_fga = sum(
            _zone(game, zone).attempts
            for game in profile["player_games"]
            for zone in FIELD_ZONES
        )
        labels: list[str] = []
        if base.spacing_score >= 90:
            labels.append("ELITE_SPACER")
        if three_per40 >= 4 and base.spacing_score >= 70:
            labels.append("HIGH_VOLUME_SHOOTER")
        if base.versatility_score >= 75 and all(zones[z].threat_score >= 0.5 for z in FIELD_ZONES):
            labels.append("THREE_LEVEL_SCORER")
        if profile["rim_pressure_score"] >= 75:
            labels.append("RIM_ATTACKER")
        if (
            total_fga > 0
            and jumper_attempts / total_fga >= 0.25
            and zones["jumper"].player_accuracy >= zones["jumper"].league_accuracy
            and zones["jumper"].attempts_per40 >= 3
        ):
            labels.append("MIDRANGE_SPECIALIST")
        if base.self_creation_score >= 80 and base.shot_making_score >= 60:
            labels.append("SELF_CREATING_SHOOTER")
        if scalability >= 80:
            labels.append("SCALABLE_SHOOTER")
        if volatility >= 80 and three_per40 >= 4:
            labels.append("VOLATILE_GUNNER")
        if base.shooting_ability_score >= 70 and profile["consistency_score"] >= 80:
            labels.append("CONSISTENT_SHOOTER")
        if profile.get("clutch_score", 0) >= 80 and profile["clutch_confidence"] >= 25:
            labels.append("CLUTCH_SCORER")
        if profile.get("postseason_score", 0) >= 80 and profile["postseason_confidence"] >= 20:
            labels.append("POSTSEASON_RISER")
        if profile.get("matchup_resistance_score", 0) >= 80 and profile["matchup_confidence"] >= 20:
            labels.append("MATCHUP_RESISTANT")
        free_throw_attempts_per40 = sum(
            _zone(game, "free_throw").attempts for game in profile["player_games"]
        ) * 40.0 / base.minutes
        if base.free_throw_score >= 90 and free_throw_attempts_per40 >= 3:
            labels.append("FREE_THROW_WEAPON")

        contextual_rows.append({
            **{key: value for key, value in profile.items() if key not in {
                "base", "player_games", "clutch_raw", "consistency_raw",
                "postseason_raw", "matchup_raw", "assisted_rate_score",
            }},
            "clutch_score": profile.get("clutch_score"),
            "consistency_score": profile["consistency_score"],
            "volatility_score": volatility,
            "selection_score": profile["selection_score"],
            "rim_pressure_score": profile["rim_pressure_score"],
            "scalability_score": min(100.0, max(0.0, scalability)),
            "postseason_score": profile.get("postseason_score"),
            "matchup_resistance_score": profile.get("matchup_resistance_score"),
            "role_labels": labels,
        })
    return game_rows, contextual_rows
