"""Compute game-level and contextual shooting signals from stored shot events."""

from __future__ import annotations

import argparse
import json
from typing import Any

import psycopg2
from psycopg2.extras import Json, execute_values

from bracketballer_data.contextual_shooting import (
    BaseProfile,
    GameContext,
    ZoneContext,
    build_contextual_profiles,
)
from bracketballer_data.database import connection_dsn, load_env_file
from bracketballer_data.import_audit import mark_failed
from bracketballer_data.model_release import validate_release_counts
from bracketballer_data.shooting_ability import MODEL_VERSION


FIRST_SEASON = 2020
LAST_SEASON = 2026

GAME_COLUMNS = (
    "player_id", "season", "model_version", "game_id", "game_start_date",
    "opponent_id", "opponent", "season_type", "tournament",
    "field_goal_attempts", "field_goals_made", "three_point_attempts",
    "three_points_made", "free_throw_attempts", "free_throws_made",
    "rim_attempts", "jumper_attempts", "points", "shooting_possessions",
    "expected_league_points", "expected_player_points",
    "execution_above_expected", "late_close_fga", "late_close_three_pa",
    "late_close_fta", "late_close_points", "late_close_expected_points",
    "assisted_perimeter_makes", "perimeter_makes",
)

CONTEXT_COLUMNS = (
    "player_id", "season", "model_version", "clutch_games", "clutch_fga",
    "clutch_three_pa", "clutch_fta", "clutch_points", "clutch_efg_pct",
    "clutch_true_shooting_pct", "clutch_points_above_expected",
    "clutch_score", "clutch_confidence", "clutch_delta_p10",
    "clutch_delta_p90", "median_game_execution", "execution_mad",
    "shooting_floor", "shooting_ceiling", "above_expectation_game_rate",
    "consistency_score", "volatility_score", "selection_value_per_100_fga",
    "selection_score", "rim_pressure_per40", "rim_pressure_score",
    "assisted_perimeter_make_rate", "scalability_score",
    "postseason_possessions", "postseason_points_above_expected",
    "postseason_score", "postseason_confidence", "strong_opponent_possessions",
    "matchup_points_above_expected", "matchup_resistance_score",
    "matchup_confidence", "role_labels",
)

CONTEXT_CONFIGURATION = {
    "clutch": {"final_minutes": 5, "max_margin": 5, "prior_attempts": 20},
    "context_reliability_possessions": {"clutch": 20, "postseason": 30, "matchup": 30},
    "opponent_defense_prior_possessions": 200,
    "strong_opponent_percentile": 75,
    "consistency_min_game_possessions": 5,
    "labels_version": 1,
}


def load_base_profiles(conn: Any, first: int, last: int, version: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT player_id, season, games, minutes, event_coverage,
                   efficiency_score, shot_making_score, spacing_score,
                   versatility_score, self_creation_score, free_throw_score,
                   confidence_score, shooting_ability_score
            FROM player_shooting_ability_profiles
            WHERE model_version = %s AND season BETWEEN %s AND %s
            ORDER BY season, player_id
            """,
            (version, first, last),
        )
        profiles = [BaseProfile(*row) for row in cursor.fetchall()]
    return {(profile.player_id, profile.season): profile for profile in profiles}


def load_games(conn: Any, first: int, last: int, version: str) -> list[GameContext]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.player_id, e.season, e.game_id, e.game_start_date,
                   e.opponent_id, e.opponent, e.season_type,
                   e.raw_payload->>'tournament' AS tournament,
                   e.shot_range,
                   COUNT(*)::int AS attempts,
                   COUNT(*) FILTER (WHERE e.made)::int AS makes,
                   COUNT(*) FILTER (WHERE
                       ((e.period = 2 AND e.seconds_remaining <= 300) OR e.period > 2)
                       AND ABS(
                           CASE WHEN (e.raw_payload->>'isHomeTeam')::boolean
                               THEN (e.raw_payload->>'homeScore')::int - (e.raw_payload->>'awayScore')::int
                               ELSE (e.raw_payload->>'awayScore')::int - (e.raw_payload->>'homeScore')::int
                           END
                           - CASE WHEN e.made THEN COALESCE((e.raw_payload->>'scoreValue')::int, 0) ELSE 0 END
                       ) <= 5
                   )::int AS clutch_attempts,
                   COUNT(*) FILTER (WHERE e.made AND
                       ((e.period = 2 AND e.seconds_remaining <= 300) OR e.period > 2)
                       AND ABS(
                           CASE WHEN (e.raw_payload->>'isHomeTeam')::boolean
                               THEN (e.raw_payload->>'homeScore')::int - (e.raw_payload->>'awayScore')::int
                               ELSE (e.raw_payload->>'awayScore')::int - (e.raw_payload->>'homeScore')::int
                           END
                           - COALESCE((e.raw_payload->>'scoreValue')::int, 0)
                       ) <= 5
                   )::int AS clutch_makes,
                   zone.league_average, zone.adjusted_accuracy,
                   zone.attempts_per40, zone.threat_score,
                   COUNT(*) FILTER (
                       WHERE e.shot_range IN ('jumper', 'three_pointer')
                         AND e.made AND e.assisted
                   )::int AS assisted_perimeter_makes,
                   COUNT(*) FILTER (
                       WHERE e.shot_range IN ('jumper', 'three_pointer') AND e.made
                   )::int AS perimeter_makes
            FROM player_shot_events e
            JOIN player_shooting_zone_profiles zone
              ON zone.player_id = e.player_id
             AND zone.season = e.season
             AND zone.model_version = %s
             AND zone.zone = e.shot_range
            WHERE e.season BETWEEN %s AND %s
            GROUP BY e.player_id, e.season, e.game_id, e.game_start_date,
                     e.opponent_id, e.opponent, e.season_type,
                     e.raw_payload->>'tournament', e.shot_range,
                     zone.league_average, zone.adjusted_accuracy,
                     zone.attempts_per40, zone.threat_score
            ORDER BY e.season, e.player_id, e.game_id, e.shot_range
            """,
            (version, first, last),
        )
        rows = cursor.fetchall()

    grouped: dict[tuple[int, int, int], dict] = {}
    for row in rows:
        (
            player_id, season, game_id, game_start_date, opponent_id, opponent,
            season_type, tournament, zone, attempts, makes, clutch_attempts,
            clutch_makes, league_accuracy, player_accuracy, attempts_per40,
            threat_score, assisted_makes, perimeter_makes,
        ) = row
        item = grouped.setdefault(
            (player_id, season, game_id),
            {
                "player_id": player_id,
                "season": season,
                "game_id": game_id,
                "game_start_date": game_start_date,
                "opponent_id": opponent_id,
                "opponent": opponent,
                "season_type": season_type,
                "tournament": tournament,
                "zones": {},
                "assisted_perimeter_makes": 0,
                "perimeter_makes": 0,
            },
        )
        item["zones"][zone] = ZoneContext(
            attempts, makes, clutch_attempts, clutch_makes,
            league_accuracy, player_accuracy, attempts_per40, threat_score,
        )
        item["assisted_perimeter_makes"] += assisted_makes
        item["perimeter_makes"] += perimeter_makes
    return [GameContext(**item) for item in grouped.values()]


def persist(
    conn: Any,
    game_rows: list[dict],
    contextual_rows: list[dict],
    first: int,
    last: int,
    version: str,
) -> None:
    game_records = [
        tuple(version if column == "model_version" else row[column] for column in GAME_COLUMNS)
        for row in game_rows
    ]
    contextual_records = []
    for row in contextual_rows:
        values = {**row, "model_version": version, "role_labels": Json(row["role_labels"])}
        contextual_records.append(tuple(values[column] for column in CONTEXT_COLUMNS))
    with conn.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM player_shooting_game_profiles
            WHERE model_version = %s AND season BETWEEN %s AND %s
            """,
            (version, first, last),
        )
        cursor.execute(
            """
            DELETE FROM player_contextual_shooting_profiles
            WHERE model_version = %s AND season BETWEEN %s AND %s
            """,
            (version, first, last),
        )
        execute_values(
            cursor,
            f"INSERT INTO player_shooting_game_profiles ({', '.join(GAME_COLUMNS)}) VALUES %s",
            game_records,
            page_size=500,
        )
        execute_values(
            cursor,
            f"INSERT INTO player_contextual_shooting_profiles ({', '.join(CONTEXT_COLUMNS)}) VALUES %s",
            contextual_records,
            page_size=500,
        )
        cursor.execute(
            """
            UPDATE shooting_model_versions
            SET configuration = configuration || %s::jsonb
            WHERE version = %s
            """,
            (Json({"contextual_signals": CONTEXT_CONFIGURATION}), version),
        )


def validate_candidate(conn: Any, version: str) -> dict[str, int]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*)::int
                 FROM player_shooting_ability_profiles
                 WHERE model_version = %s),
                (SELECT COUNT(*)::int
                 FROM player_shooting_zone_profiles
                 WHERE model_version = %s),
                (SELECT COUNT(*)::int
                 FROM player_shooting_game_profiles
                 WHERE model_version = %s),
                (SELECT COUNT(*)::int
                 FROM player_contextual_shooting_profiles
                 WHERE model_version = %s)
            """,
            (version, version, version, version),
        )
        ability, zones, games, contextual = cursor.fetchone()
    counts = {
        "ability_profiles": ability,
        "zone_profiles": zones,
        "game_profiles": games,
        "contextual_profiles": contextual,
    }
    validate_release_counts(counts)
    return counts


def activate_candidate(conn: Any, version: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE shooting_model_versions SET is_active = FALSE WHERE is_active"
        )
        cursor.execute(
            """
            UPDATE shooting_model_versions
            SET is_active = TRUE, activated_at = now()
            WHERE version = %s
            """,
            (version,),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"Unknown shooting model version: {version}")


def publish_audit_run(
    conn: Any,
    run_id: int,
    counts: dict[str, int],
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE data_import_runs
            SET status = 'published',
                published_row_counts = %s::jsonb,
                validation_results = validation_results || %s::jsonb,
                validated_at = now(),
                published_at = now(),
                finished_at = now()
            WHERE id = %s
              AND dataset = 'shooting_model'
              AND status = 'running'
              AND source_sha256 IS NOT NULL
            """,
            (
                json.dumps(counts, sort_keys=True),
                json.dumps({"complete_candidate": True}, sort_keys=True),
                run_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Shooting model audit run {run_id} is not publishable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=int, default=FIRST_SEASON)
    parser.add_argument("--last", type=int, default=LAST_SEASON)
    parser.add_argument("--version", default=MODEL_VERSION)
    parser.add_argument("--draws", type=int, default=2_000)
    args = parser.parse_args()
    if args.first > args.last:
        parser.error("--first cannot exceed --last")
    if args.draws < 100:
        parser.error("--draws must be at least 100")

    load_env_file()
    conn = psycopg2.connect(connection_dsn())
    conn.autocommit = False
    run_id: int | None = None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM shooting_model_versions WHERE version = %s",
                (args.version,),
            )
            candidate = cursor.fetchone()
            cursor.execute(
                """
                SELECT id
                FROM data_import_runs
                WHERE dataset = 'shooting_model'
                  AND model_version = %s
                  AND status = 'running'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (args.version,),
            )
            audit = cursor.fetchone()
        if candidate is None:
            raise ValueError(
                f"Unknown candidate {args.version}; compute ability profiles first"
            )
        if audit is None:
            raise ValueError(f"Candidate {args.version} has no running audit record")
        run_id = audit[0]
        version = args.version
        bases = load_base_profiles(conn, args.first, args.last, version)
        games = load_games(conn, args.first, args.last, version)
        game_rows, contextual_rows = build_contextual_profiles(
            games, bases, model_version=version, draws=args.draws
        )
        persist(conn, game_rows, contextual_rows, args.first, args.last, version)
        release_counts = validate_candidate(conn, version)
        activate_candidate(conn, version)
        publish_audit_run(conn, run_id, release_counts)
        conn.commit()
    except Exception as error:
        if run_id is not None:
            mark_failed(conn, run_id, error)
        else:
            conn.rollback()
        raise
    finally:
        conn.close()
    print(f"Activated complete candidate {version}")
    print(f"Stored {release_counts['game_profiles']:,} game profiles")
    print(f"Stored {release_counts['contextual_profiles']:,} contextual profiles")


if __name__ == "__main__":
    main()
