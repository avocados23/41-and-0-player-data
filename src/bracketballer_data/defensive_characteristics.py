"""Transparent, season-relative defensive characteristic scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

CHARACTERISTIC_KEYS = (
    "RIM_PROTECTOR",
    "DEFENSIVE_GLASS_CLEANER",
    "DEFENSIVE_DISRUPTOR",
    "DROP_COMPATIBLE_BIG",
    "LIKELY_DROP_ANCHOR",
)

MODEL_CONFIGURATION = {
    "minimum_scheme_possessions": 300,
    "minimum_scheme_confidence": 60,
    "reliability_prior_possessions": 400,
    "scheme_confidence_cap": 85,
    "rim_protector_weights": {
        "interior_accuracy_suppression": 0.35,
        "interior_attempt_deterrence": 0.25,
        "block_rate": 0.20,
        "defensive_rebound_rate": 0.10,
        "defensive_prior": 0.10,
    },
    "drop_compatible_weights": {
        "center_role_fit": 0.40,
        "rim_protector": 0.30,
        "rebounding": 0.15,
        "foul_control": 0.15,
    },
    "drop_scheme_weights": {
        "interior_attempt_deterrence": 0.60,
        "two_point_jumper_concession": 0.40,
    },
    "drop_anchor_weights": {
        "drop_compatible": 0.35,
        "scheme_evidence": 0.30,
        "defensive_impact": 0.35,
    },
}


@dataclass(frozen=True)
class PlayerDefensiveEvidence:
    player_id: int
    team_id: int
    season: int
    games: int
    season_games: int
    possessions: float
    center_role_share: float
    height: float | None
    block_pct: float | None
    steal_pct: float | None
    defensive_rebound_pct: float | None
    dporpag: float | None
    dbpm: float | None
    fouls_per40: float | None
    interior_attempt_rate_delta: float
    interior_accuracy_delta: float
    jumper_attempt_rate_delta: float
    opponent_offensive_rebound_pct_delta: float
    opponent_turnover_rate_delta: float
    opponent_free_throw_rate_delta: float
    adjusted_defense_rating_delta: float
    finalized_game_coverage: float
    lineup_coverage: float
    data_through_date: str | None = None


@dataclass(frozen=True)
class CharacteristicScore:
    player_id: int
    team_id: int
    season: int
    key: str
    score: float
    confidence: float
    qualified: bool
    games: int
    possessions: float
    evidence: dict[str, float]
    limitations: tuple[str, ...]
    data_through_date: str | None


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    return min(maximum, max(minimum, value))


def _rank(values: list[float], value: float) -> float:
    if len(values) <= 1:
        return 50.0
    below = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    return 100.0 * (below + 0.5 * max(0, equal - 1)) / (len(values) - 1)


def _number(value: float | None, default: float = 0.0) -> float:
    return default if value is None else float(value)


def _weighted(parts: dict[str, float], weights: dict[str, float]) -> float:
    return sum(parts[key] * weight for key, weight in weights.items())


def _confidence(
    row: PlayerDefensiveEvidence,
    *,
    role_sensitive: bool,
) -> float:
    prior = MODEL_CONFIGURATION["reliability_prior_possessions"]
    reliability = row.possessions / (row.possessions + prior)
    game_coverage = (
        min(1.0, row.games / row.season_games) if row.season_games > 0 else 1.0
    )
    role_certainty = (
        max(0.25, min(1.0, row.center_role_share)) if role_sensitive else 1.0
    )
    return clamp(
        100
        * reliability
        * min(1.0, max(0.0, row.finalized_game_coverage))
        * min(1.0, max(0.0, row.lineup_coverage))
        * game_coverage
        * role_certainty
    )


def score_characteristics(
    rows: Iterable[PlayerDefensiveEvidence],
    *,
    scheme_validated: bool = False,
) -> list[CharacteristicScore]:
    population = list(rows)
    if not population:
        return []
    seasons = sorted({row.season for row in population})
    if len(seasons) > 1:
        return [
            score
            for season in seasons
            for score in score_characteristics(
                (row for row in population if row.season == season),
                scheme_validated=scheme_validated,
            )
        ]

    metrics = {
        "deterrence": [-row.interior_attempt_rate_delta for row in population],
        "suppression": [-row.interior_accuracy_delta for row in population],
        "jumper": [row.jumper_attempt_rate_delta for row in population],
        "orb": [-row.opponent_offensive_rebound_pct_delta for row in population],
        "turnover": [row.opponent_turnover_rate_delta for row in population],
        "foul": [
            -(
                _number(row.fouls_per40)
                + 10 * row.opponent_free_throw_rate_delta
            )
            for row in population
        ],
        "defense": [-row.adjusted_defense_rating_delta for row in population],
        "block": [_number(row.block_pct) for row in population],
        "steal": [_number(row.steal_pct) for row in population],
        "drb": [_number(row.defensive_rebound_pct) for row in population],
        "prior": [
            _number(row.dporpag) + 0.5 * _number(row.dbpm)
            for row in population
        ],
        "height": [_number(row.height) for row in population if row.height],
    }

    results: list[CharacteristicScore] = []
    for row in population:
        components = {
            "interior_attempt_deterrence": _rank(
                metrics["deterrence"], -row.interior_attempt_rate_delta
            ),
            "interior_accuracy_suppression": _rank(
                metrics["suppression"], -row.interior_accuracy_delta
            ),
            "two_point_jumper_concession": _rank(
                metrics["jumper"], row.jumper_attempt_rate_delta
            ),
            "offensive_rebound_suppression": _rank(
                metrics["orb"], -row.opponent_offensive_rebound_pct_delta
            ),
            "turnover_lift": _rank(
                metrics["turnover"], row.opponent_turnover_rate_delta
            ),
            "foul_control": _rank(
                metrics["foul"],
                -(
                    _number(row.fouls_per40)
                    + 10 * row.opponent_free_throw_rate_delta
                ),
            ),
            "defensive_impact": _rank(
                metrics["defense"], -row.adjusted_defense_rating_delta
            ),
            "block_rate": _rank(metrics["block"], _number(row.block_pct)),
            "steal_rate": _rank(metrics["steal"], _number(row.steal_pct)),
            "defensive_rebound_rate": _rank(
                metrics["drb"], _number(row.defensive_rebound_pct)
            ),
            "defensive_prior": _rank(
                metrics["prior"],
                _number(row.dporpag) + 0.5 * _number(row.dbpm),
            ),
            "height": (
                _rank(metrics["height"], _number(row.height))
                if row.height and metrics["height"]
                else 50.0
            ),
        }
        reliability = row.possessions / (
            row.possessions
            + MODEL_CONFIGURATION["reliability_prior_possessions"]
        )
        components = {
            key: 50.0 + reliability * (value - 50.0)
            for key, value in components.items()
        }
        components["center_role_fit"] = clamp(
            70 * row.center_role_share + 0.30 * components["height"]
        )
        rim = _weighted(
            components,
            MODEL_CONFIGURATION["rim_protector_weights"],
        )
        glass = (
            0.60 * components["defensive_rebound_rate"]
            + 0.40 * components["offensive_rebound_suppression"]
        )
        disruptor = (
            0.50 * components["steal_rate"]
            + 0.25 * components["block_rate"]
            + 0.25 * components["turnover_lift"]
        )
        drop_compatible_parts = {
            "center_role_fit": components["center_role_fit"],
            "rim_protector": rim,
            "rebounding": glass,
            "foul_control": components["foul_control"],
        }
        drop_compatible = _weighted(
            drop_compatible_parts,
            MODEL_CONFIGURATION["drop_compatible_weights"],
        )
        scheme_parts = {
            "interior_attempt_deterrence": components[
                "interior_attempt_deterrence"
            ],
            "two_point_jumper_concession": components[
                "two_point_jumper_concession"
            ],
        }
        scheme = _weighted(
            scheme_parts,
            MODEL_CONFIGURATION["drop_scheme_weights"],
        )
        impact = (
            0.50 * components["interior_accuracy_suppression"]
            + 0.30 * components["defensive_impact"]
            + 0.20 * components["offensive_rebound_suppression"]
        )
        anchor_parts = {
            "drop_compatible": drop_compatible,
            "scheme_evidence": scheme,
            "defensive_impact": impact,
        }
        anchor = _weighted(
            anchor_parts,
            MODEL_CONFIGURATION["drop_anchor_weights"],
        )

        general_confidence = _confidence(row, role_sensitive=False)
        role_confidence = _confidence(row, role_sensitive=True)
        scheme_confidence = min(
            MODEL_CONFIGURATION["scheme_confidence_cap"],
            role_confidence,
        )
        specifications = (
            ("RIM_PROTECTOR", rim, general_confidence, components),
            (
                "DEFENSIVE_GLASS_CLEANER",
                glass,
                general_confidence,
                {
                    "defensive_rebound_rate": components[
                        "defensive_rebound_rate"
                    ],
                    "offensive_rebound_suppression": components[
                        "offensive_rebound_suppression"
                    ],
                },
            ),
            (
                "DEFENSIVE_DISRUPTOR",
                disruptor,
                general_confidence,
                {
                    "steal_rate": components["steal_rate"],
                    "block_rate": components["block_rate"],
                    "turnover_lift": components["turnover_lift"],
                },
            ),
            (
                "DROP_COMPATIBLE_BIG",
                drop_compatible,
                role_confidence,
                drop_compatible_parts,
            ),
            ("LIKELY_DROP_ANCHOR", anchor, scheme_confidence, anchor_parts),
        )
        for key, score, confidence, evidence in specifications:
            limitations = []
            if row.possessions < 300:
                limitations.append("SMALL_LINEUP_SAMPLE")
            if row.lineup_coverage < 0.8:
                limitations.append("INCOMPLETE_LINEUP_COVERAGE")
            if key == "LIKELY_DROP_ANCHOR":
                limitations.append("SCHEME_INFERRED_NOT_OBSERVED")
                if not scheme_validated:
                    limitations.append("SCHEME_LABEL_NOT_VALIDATED")
                qualified = (
                    scheme_validated
                    and row.possessions
                    >= MODEL_CONFIGURATION["minimum_scheme_possessions"]
                    and confidence
                    >= MODEL_CONFIGURATION["minimum_scheme_confidence"]
                    and score >= 70
                )
            else:
                qualified = (
                    row.possessions >= 150 and confidence >= 45 and score >= 70
                )
            results.append(
                CharacteristicScore(
                    player_id=row.player_id,
                    team_id=row.team_id,
                    season=row.season,
                    key=key,
                    score=round(clamp(score), 3),
                    confidence=round(confidence, 3),
                    qualified=qualified,
                    games=row.games,
                    possessions=round(row.possessions, 3),
                    evidence={
                        component: round(value, 3)
                        for component, value in evidence.items()
                    },
                    limitations=tuple(limitations),
                    data_through_date=row.data_through_date,
                )
            )
    return results
