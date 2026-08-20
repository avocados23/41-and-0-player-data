"""Pure player and lineup shooting-ability calculations.

The database jobs and Fastify service intentionally consume the same stored
components. Nothing in this module performs I/O.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np


MODEL_VERSION = "shooting-v1"
ZONES = ("rim", "jumper", "three_pointer", "free_throw")
FIELD_GOAL_ZONES = ZONES[:3]
ZONE_POINT_VALUES = {"rim": 2.0, "jumper": 2.0, "three_pointer": 3.0, "free_throw": 1.0}
PRIOR_ATTEMPTS = 50.0
THREAT_MARGIN = 0.02
THREAT_VOLUME_TARGETS = {"rim": 4.0, "jumper": 3.0, "three_pointer": 4.0}
PLAYER_MONTE_CARLO_DRAWS = 10_000
LINEUP_MONTE_CARLO_DRAWS = 5_000

MODEL_CONFIGURATION = {
    "prior_attempts": PRIOR_ATTEMPTS,
    "threat_margin": THREAT_MARGIN,
    "threat_volume_targets_per40": THREAT_VOLUME_TARGETS,
    "reference_min_games_exclusive": 18,
    "player_monte_carlo_draws": PLAYER_MONTE_CARLO_DRAWS,
    "lineup_monte_carlo_draws": LINEUP_MONTE_CARLO_DRAWS,
    "player_weights": {
        "shot_making": 0.45,
        "spacing": 0.35,
        "versatility": 0.15,
        "free_throw": 0.05,
    },
    "lineup_weights": {
        "efficiency": 0.55,
        "spacing": 0.25,
        "creation": 0.10,
        "versatility": 0.10,
    },
}


@dataclass(frozen=True)
class ZoneCount:
    attempts: int = 0
    makes: int = 0


@dataclass(frozen=True)
class PlayerShootingInput:
    player_id: int
    season: int
    games: int
    minutes: int
    box_fga: int
    box_fta: int
    zones: Mapping[str, ZoneCount]
    assisted_perimeter_makes: int = 0
    perimeter_makes: int = 0


def percent_ranks(values: Iterable[float]) -> list[float]:
    """SQL PERCENT_RANK semantics, expressed on a 0-100 scale."""
    rows = list(values)
    if len(rows) <= 1:
        return [50.0] * len(rows)
    first: dict[float, int] = {}
    for position, value in enumerate(sorted(rows)):
        first.setdefault(value, position)
    denominator = len(rows) - 1
    return [100.0 * first[value] / denominator for value in rows]


def _zscore(value: float, values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / len(values)
    return 0.0 if variance <= 0 else (value - mean) / math.sqrt(variance)


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / len(values)
    return mean, math.sqrt(variance) if variance > 0 else 0.0


def _percentiles_against(values: list[float], reference: list[float]) -> list[float]:
    if not reference:
        return [50.0] * len(values)
    ordered = np.sort(np.asarray(reference))
    denominator = max(1, len(ordered) - 1)
    return [
        100.0 * min(len(ordered) - 1, int(np.searchsorted(ordered, value, side="left"))) / denominator
        for value in values
    ]


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1e-300 if abs(d) < 1e-300 else d
    d = 1.0 / d
    result = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1e-300 if abs(d) < 1e-300 else d
        c = 1.0 + aa / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        result *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1e-300 if abs(d) < 1e-300 else d
        c = 1.0 + aa / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        delta = d * c
        result *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return result


def regularized_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta I_x(a,b), without a SciPy dependency."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def beta_probability_above(alpha: float, beta: float, threshold: float) -> float:
    return min(1.0, max(0.0, 1.0 - regularized_beta(threshold, alpha, beta)))


def _coverage(event_fga: int, event_fta: int, box_fga: int, box_fta: int) -> float:
    pairs = ((event_fga, box_fga), (event_fta, box_fta))
    weight = sum(max(event, box) for event, box in pairs)
    if weight == 0:
        return 0.0
    matched = sum(min(event, box) for event, box in pairs)
    return matched / weight


def _stable_seed(player_id: int, season: int, version: str = MODEL_VERSION) -> int:
    digest = hashlib.sha256(f"{version}:{season}:{player_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def build_ability_profiles(
    inputs: Iterable[PlayerShootingInput],
    *,
    draws: int = PLAYER_MONTE_CARLO_DRAWS,
    model_version: str = MODEL_VERSION,
) -> list[dict]:
    """Build complete season-relative player profiles and four zone rows."""
    usable = [
        row for row in inputs
        if row.minutes > 0 and sum(row.zones.get(z, ZoneCount()).attempts for z in ZONES) > 0
    ]
    by_season: dict[int, list[PlayerShootingInput]] = {}
    for row in usable:
        by_season.setdefault(row.season, []).append(row)

    output: list[dict] = []
    for season, season_rows in sorted(by_season.items()):
        season_rows.sort(key=lambda row: row.player_id)
        reference = [row for row in season_rows if row.games > 18] or season_rows
        baselines: dict[str, float] = {}
        for zone in ZONES:
            attempts = sum(row.zones.get(zone, ZoneCount()).attempts for row in reference)
            makes = sum(row.zones.get(zone, ZoneCount()).makes for row in reference)
            baselines[zone] = min(0.99, max(0.01, makes / attempts if attempts else 0.5))

        working: list[dict] = []
        for row in season_rows:
            fga = sum(row.zones.get(z, ZoneCount()).attempts for z in FIELD_GOAL_ZONES)
            fta = row.zones.get("free_throw", ZoneCount()).attempts
            total_attempts = fga + fta
            zones: dict[str, dict] = {}
            for zone in ZONES:
                count = row.zones.get(zone, ZoneCount())
                mu = baselines[zone]
                prior_alpha = PRIOR_ATTEMPTS * mu
                prior_beta = PRIOR_ATTEMPTS * (1.0 - mu)
                alpha = count.makes + prior_alpha
                beta = count.attempts - count.makes + prior_beta
                adjusted = alpha / (alpha + beta)
                per40 = 40.0 * count.attempts / row.minutes
                if zone in FIELD_GOAL_ZONES:
                    target = THREAT_VOLUME_TARGETS[zone]
                    probability = beta_probability_above(alpha, beta, max(0.0, mu - THREAT_MARGIN))
                    threat = probability * min(1.0, per40 / target)
                else:
                    probability, threat = 0.0, 0.0
                zones[zone] = {
                    "zone": zone,
                    "attempts": count.attempts,
                    "makes": count.makes,
                    "attempts_per40": per40,
                    "attempt_share": count.attempts / total_attempts if total_attempts else 0.0,
                    "league_average": mu,
                    "prior_alpha": prior_alpha,
                    "prior_beta": prior_beta,
                    "posterior_alpha": alpha,
                    "posterior_beta": beta,
                    "adjusted_accuracy": adjusted,
                    "threat_probability": probability,
                    "threat_score": threat,
                }

            expected_fga = 100.0 * sum(
                (zones[z]["attempts"] / fga if fga else 0.0)
                * ZONE_POINT_VALUES[z] * zones[z]["adjusted_accuracy"]
                for z in FIELD_GOAL_ZONES
            )
            denominator = fga + 0.44 * fta
            expected_possessions = 100.0 * sum(
                zones[z]["attempts"] * ZONE_POINT_VALUES[z] * zones[z]["adjusted_accuracy"]
                for z in ZONES
            ) / denominator if denominator else 0.0
            shot_making = 100.0 * sum(
                (zones[z]["attempts"] / fga if fga else 0.0)
                * ZONE_POINT_VALUES[z]
                * (zones[z]["adjusted_accuracy"] - baselines[z])
                for z in FIELD_GOAL_ZONES
            )
            spacing_raw = zones["three_pointer"]["threat_probability"] * math.sqrt(
                min(1.0, zones["three_pointer"]["attempts_per40"] / 4.0)
            )
            versatility_raw = math.prod(zones[z]["threat_score"] for z in FIELD_GOAL_ZONES) ** (1.0 / 3.0)
            unassisted = max(0, row.perimeter_makes - row.assisted_perimeter_makes)
            creation_volume = 40.0 * unassisted / row.minutes
            creation_share = unassisted / row.perimeter_makes if row.perimeter_makes else 0.0
            reliability = sum(
                zones[z]["attempt_share"]
                * zones[z]["attempts"] / (zones[z]["attempts"] + PRIOR_ATTEMPTS)
                for z in ZONES
            )
            working.append({
                "input": row,
                "zones": zones,
                "fga": fga,
                "fta": fta,
                "expected_fga": expected_fga,
                "expected_possessions": expected_possessions,
                "shot_making": shot_making,
                "spacing_raw": spacing_raw,
                "versatility_raw": versatility_raw,
                "creation_volume": creation_volume,
                "creation_share": creation_share,
                "confidence": 100.0 * _coverage(fga, fta, row.box_fga, row.box_fta) * reliability,
            })

        metric_names = ("expected_possessions", "shot_making", "spacing_raw", "versatility_raw")
        reference_working = [item for item in working if item["input"].games > 18] or working
        ranks = {
            name: _percentiles_against(
                [item[name] for item in working],
                [item[name] for item in reference_working],
            )
            for name in metric_names
        }
        ft_values = [item["zones"]["free_throw"]["adjusted_accuracy"] for item in working]
        reference_ft_values = [item["zones"]["free_throw"]["adjusted_accuracy"] for item in reference_working]
        ft_ranks = _percentiles_against(ft_values, reference_ft_values)
        creation_volume_ranks = _percentiles_against(
            [item["creation_volume"] for item in working],
            [item["creation_volume"] for item in reference_working],
        )
        creation_share_ranks = _percentiles_against(
            [item["creation_share"] for item in working],
            [item["creation_share"] for item in reference_working],
        )
        reference_values = {
            name: [item[name] for item in working if item["input"].games > 18] or [item[name] for item in working]
            for name in ("shot_making", "spacing_raw", "versatility_raw")
        }
        reference_ft = [
            item["zones"]["free_throw"]["adjusted_accuracy"]
            for item in working if item["input"].games > 18
        ] or ft_values
        reference_stats = {
            name: _mean_std(values) for name, values in reference_values.items()
        }
        reference_ft_stats = _mean_std(reference_ft)
        latents = [
            0.45 * _zscore(item["shot_making"], reference_values["shot_making"])
            + 0.35 * _zscore(item["spacing_raw"], reference_values["spacing_raw"])
            + 0.15 * _zscore(item["versatility_raw"], reference_values["versatility_raw"])
            + 0.05 * _zscore(item["zones"]["free_throw"]["adjusted_accuracy"], reference_ft)
            for item in working
        ]
        reference_latents = [
            latent for latent, item in zip(latents, working)
            if item["input"].games > 18
        ] or latents
        ability_scores = _percentiles_against(latents, reference_latents)
        sorted_latents = np.sort(np.asarray(reference_latents))

        for index, item in enumerate(working):
            row = item["input"]
            zones = item["zones"]
            rng = np.random.default_rng(
                _stable_seed(row.player_id, row.season, model_version)
            )
            samples = {
                z: rng.beta(zones[z]["posterior_alpha"], zones[z]["posterior_beta"], draws)
                for z in ZONES
            }
            fga = item["fga"]
            fta = item["fta"]
            denominator = fga + 0.44 * fta
            expected_draws = 100.0 * sum(
                zones[z]["attempts"] * ZONE_POINT_VALUES[z] * samples[z]
                for z in ZONES
            ) / denominator
            shot_draws = 100.0 * sum(
                (zones[z]["attempts"] / fga if fga else 0.0)
                * ZONE_POINT_VALUES[z] * (samples[z] - baselines[z])
                for z in FIELD_GOAL_ZONES
            )
            volume_factors = {
                z: min(1.0, zones[z]["attempts_per40"] / THREAT_VOLUME_TARGETS[z])
                for z in FIELD_GOAL_ZONES
            }
            spacing_draws = (samples["three_pointer"] >= baselines["three_pointer"] - THREAT_MARGIN) * math.sqrt(volume_factors["three_pointer"])
            versatility_draws = np.prod(np.vstack([
                (samples[z] >= baselines[z] - THREAT_MARGIN) * volume_factors[z]
                for z in FIELD_GOAL_ZONES
            ]), axis=0) ** (1.0 / 3.0)
            def standardized(values: np.ndarray, stats: tuple[float, float]) -> np.ndarray:
                mean, std = stats
                return np.zeros_like(values, dtype=float) if std == 0 else (values - mean) / std

            latent_draws = (
                0.45 * standardized(shot_draws, reference_stats["shot_making"])
                + 0.35 * standardized(spacing_draws, reference_stats["spacing_raw"])
                + 0.15 * standardized(versatility_draws, reference_stats["versatility_raw"])
                + 0.05 * standardized(samples["free_throw"], reference_ft_stats)
            )
            ability_draws = 100.0 * np.searchsorted(sorted_latents, latent_draws, side="right") / len(sorted_latents)
            ability_quantiles = np.quantile(ability_draws, [0.1, 0.5, 0.9])
            expected_quantiles = np.quantile(expected_draws, [0.1, 0.5, 0.9])
            output.append({
                "player_id": row.player_id,
                "season": row.season,
                "games": row.games,
                "minutes": row.minutes,
                "tracked_events": item["fga"] + item["fta"],
                "field_goal_attempts": item["fga"],
                "free_throw_attempts": item["fta"],
                "field_goal_attempts_per40": 40.0 * item["fga"] / row.minutes,
                "event_coverage": _coverage(item["fga"], item["fta"], row.box_fga, row.box_fta),
                "expected_points_per_100_fga": item["expected_fga"],
                "expected_points_per_100_shooting_possessions": item["expected_possessions"],
                "efficiency_score": ranks["expected_possessions"][index],
                "shot_making_above_average": item["shot_making"],
                "shot_making_score": ranks["shot_making"][index],
                "spacing_score": ranks["spacing_raw"][index],
                "versatility_score": ranks["versatility_raw"][index],
                "self_creation_score": 0.6 * creation_volume_ranks[index] + 0.4 * creation_share_ranks[index],
                "free_throw_score": ft_ranks[index],
                "confidence_score": min(100.0, max(0.0, item["confidence"])),
                "shooting_ability_score": ability_scores[index],
                "ability_p10": float(ability_quantiles[0]),
                "ability_p50": float(ability_quantiles[1]),
                "ability_p90": float(ability_quantiles[2]),
                "expected_points_p10": float(expected_quantiles[0]),
                "expected_points_p50": float(expected_quantiles[1]),
                "expected_points_p90": float(expected_quantiles[2]),
                "zones": list(zones.values()),
            })
    return output
