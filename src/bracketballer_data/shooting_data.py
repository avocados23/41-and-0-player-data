"""Pure CBBD shot-event transformation and shooter-scoring helpers."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


THREE_POINT_RANGE = "three_pointer"
FREE_THROW_RANGE = "free_throw"
ACCURACY_PRIOR_ATTEMPTS = 50
SHOOTER_MIN_THREE_POINT_ATTEMPTS = 50
SHOOTER_SCORE_THRESHOLD = 75


EVENT_DB_COLUMNS = (
    "source_play_id",
    "source_id",
    "player_id",
    "season",
    "game_id",
    "game_source_id",
    "game_start_date",
    "season_type",
    "play_type",
    "team_id",
    "team",
    "opponent_id",
    "opponent",
    "period",
    "clock",
    "seconds_remaining",
    "play_text",
    "made",
    "shot_range",
    "assisted",
    "assisted_by_player_id",
    "assisted_by_name",
    "location_x",
    "location_y",
    "raw_payload",
)


def _nested(value: Mapping[str, Any] | None, *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def normalize_play(
    raw: Mapping[str, Any], requested_player_id: int, requested_season: int
) -> dict[str, Any]:
    """Flatten a CBBD PlayInfo JSON object into player_shot_events columns.

    CBBD's player endpoint is expected to return shots taken by the requested
    player. Reject a conflicting shooter id instead of silently assigning a
    teammate's event to that player.
    """
    shot_info = raw.get("shotInfo") or raw.get("shot_info") or {}
    shooter_id = _nested(shot_info, "shooter", "id")
    if shooter_id is not None and int(shooter_id) != int(requested_player_id):
        raise ValueError(
            f"CBBD play {raw.get('id')} shooter {shooter_id} does not match "
            f"requested player {requested_player_id}"
        )

    source_play_id = raw.get("id")
    game_id = raw.get("gameId", raw.get("game_id"))
    if source_play_id is None or game_id is None:
        raise ValueError("CBBD play is missing required id or gameId")

    assisted_by = shot_info.get("assistedBy") or shot_info.get("assisted_by") or {}
    location = shot_info.get("location") or {}
    season = raw.get("season", requested_season)

    return {
        "source_play_id": int(source_play_id),
        "source_id": str(raw.get("sourceId", raw.get("source_id", source_play_id))),
        "player_id": int(requested_player_id),
        "season": int(season),
        "game_id": int(game_id),
        "game_source_id": raw.get("gameSourceId", raw.get("game_source_id")),
        "game_start_date": raw.get("gameStartDate", raw.get("game_start_date")),
        "season_type": raw.get("seasonType", raw.get("season_type")),
        "play_type": raw.get("playType", raw.get("play_type")),
        "team_id": raw.get("teamId", raw.get("team_id")),
        "team": raw.get("team"),
        "opponent_id": raw.get("opponentId", raw.get("opponent_id")),
        "opponent": raw.get("opponent"),
        "period": raw.get("period"),
        "clock": raw.get("clock"),
        "seconds_remaining": raw.get(
            "secondsRemaining", raw.get("seconds_remaining")
        ),
        "play_text": raw.get("playText", raw.get("play_text")),
        "made": shot_info.get("made"),
        "shot_range": shot_info.get("range"),
        "assisted": shot_info.get("assisted"),
        "assisted_by_player_id": assisted_by.get("id"),
        "assisted_by_name": assisted_by.get("name"),
        "location_x": location.get("x"),
        "location_y": location.get("y"),
        "raw_payload": dict(raw),
    }


def event_record(event: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return an event in the exact database insert column order."""
    return tuple(event[column] for column in EVENT_DB_COLUMNS)


def normalize_eligible_plays(
    raw_plays: Iterable[Mapping[str, Any]],
    eligible_player_ids: set[int],
    season: int,
) -> list[dict[str, Any]]:
    """Filter a bulk play response to database shooters and deduplicate it."""
    by_id: dict[int, dict[str, Any]] = {}
    for raw in raw_plays:
        raw_season = raw.get("season")
        if raw_season is not None and int(raw_season) != season:
            continue
        shot_info = raw.get("shotInfo") or raw.get("shot_info") or {}
        shooter_id = _nested(shot_info, "shooter", "id")
        if shooter_id is None or int(shooter_id) not in eligible_player_ids:
            continue
        event = normalize_play(raw, int(shooter_id), season)
        by_id[event["source_play_id"]] = event
    return list(by_id.values())


@dataclass(frozen=True)
class ShootingAggregate:
    player_id: int
    season: int
    games: int
    shooting_events: int
    field_goal_attempts: int
    free_throw_attempts: int
    three_point_attempts: int
    three_point_made: int
    assisted_three_made: int
    coordinate_field_goal_attempts: int


def _percent_ranks(values: list[float]) -> list[float]:
    """Return SQL-style PERCENT_RANK values, using the first rank for ties."""
    if len(values) <= 1:
        return [0.0] * len(values)
    first_position: dict[float, int] = {}
    for position, value in enumerate(sorted(values)):
        first_position.setdefault(value, position)
    denominator = len(values) - 1
    return [first_position[value] / denominator for value in values]


def build_shooting_profiles(
    aggregates: Iterable[ShootingAggregate],
) -> list[dict[str, Any]]:
    """Build season-relative shooter profiles from event aggregates."""
    by_season: dict[int, list[ShootingAggregate]] = defaultdict(list)
    for aggregate in aggregates:
        by_season[aggregate.season].append(aggregate)

    profiles: list[dict[str, Any]] = []
    for season in sorted(by_season):
        rows = sorted(by_season[season], key=lambda item: item.player_id)
        total_three_attempts = sum(row.three_point_attempts for row in rows)
        total_three_made = sum(row.three_point_made for row in rows)
        season_mean = (
            total_three_made / total_three_attempts if total_three_attempts else 0.0
        )

        volumes: list[float] = []
        adjusted_accuracies: list[float] = []
        shares: list[float] = []
        for row in rows:
            volumes.append(
                row.three_point_attempts / row.games if row.games > 0 else 0.0
            )
            adjusted_accuracies.append(
                (row.three_point_made + season_mean * ACCURACY_PRIOR_ATTEMPTS)
                / (row.three_point_attempts + ACCURACY_PRIOR_ATTEMPTS)
            )
            shares.append(
                row.three_point_attempts / row.field_goal_attempts
                if row.field_goal_attempts
                else 0.0
            )

        volume_percentiles = _percent_ranks(volumes)
        accuracy_percentiles = _percent_ranks(adjusted_accuracies)
        share_percentiles = _percent_ranks(shares)

        for index, row in enumerate(rows):
            weighted = 100 * (
                0.50 * volume_percentiles[index]
                + 0.35 * accuracy_percentiles[index]
                + 0.15 * share_percentiles[index]
            )
            score = min(100, max(0, int(math.floor(weighted + 0.5))))
            raw_pct = (
                row.three_point_made / row.three_point_attempts
                if row.three_point_attempts
                else None
            )
            profiles.append(
                {
                    "player_id": row.player_id,
                    "season": row.season,
                    "shooting_events": row.shooting_events,
                    "field_goal_attempts": row.field_goal_attempts,
                    "free_throw_attempts": row.free_throw_attempts,
                    "three_point_attempts": row.three_point_attempts,
                    "three_point_made": row.three_point_made,
                    "raw_three_point_pct": raw_pct,
                    "adjusted_three_point_pct": adjusted_accuracies[index],
                    "three_point_attempts_pg": volumes[index],
                    "three_point_attempt_share": shares[index],
                    "assisted_three_rate": (
                        row.assisted_three_made / row.three_point_made
                        if row.three_point_made
                        else None
                    ),
                    "coordinate_coverage": (
                        row.coordinate_field_goal_attempts / row.field_goal_attempts
                        if row.field_goal_attempts
                        else None
                    ),
                    "shooter_score": score,
                    "is_shooter": (
                        row.three_point_attempts
                        >= SHOOTER_MIN_THREE_POINT_ATTEMPTS
                        and score >= SHOOTER_SCORE_THRESHOLD
                    ),
                }
            )
    return profiles
