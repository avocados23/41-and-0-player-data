"""Compute and persist versioned shooting-ability profiles.

This reads only previously ingested CBBD events. It never calls CBBD and can be
rerun without refetching a completed season.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, execute_values

from bracketballer_data.database import connection_dsn, load_env_file
from bracketballer_data.import_audit import (
    begin_import_run,
    mark_failed,
    pipeline_commit,
    update_running_import,
)
from bracketballer_data.shooting_ability import (
    MODEL_CONFIGURATION,
    MODEL_VERSION,
    ZONES,
    PlayerShootingInput,
    ZoneCount,
    build_ability_profiles,
)
from bracketballer_data.paths import REPO_ROOT


FIRST_SEASON = 2020
LAST_SEASON = 2026

PROFILE_COLUMNS = (
    "player_id", "season", "model_version", "games", "minutes",
    "tracked_events", "field_goal_attempts", "free_throw_attempts",
    "field_goal_attempts_per40", "event_coverage",
    "expected_points_per_100_fga",
    "expected_points_per_100_shooting_possessions", "efficiency_score",
    "shot_making_above_average", "shot_making_score", "spacing_score",
    "versatility_score", "self_creation_score", "free_throw_score",
    "confidence_score", "shooting_ability_score", "ability_p10",
    "ability_p50", "ability_p90", "expected_points_p10",
    "expected_points_p50", "expected_points_p90",
)

ZONE_COLUMNS = (
    "player_id", "season", "model_version", "zone", "attempts", "makes",
    "attempts_per40", "attempt_share", "league_average", "prior_alpha",
    "prior_beta", "posterior_alpha", "posterior_beta", "adjusted_accuracy",
    "threat_probability", "threat_score",
)


def load_inputs(conn: Any, first: int, last: int) -> list[PlayerShootingInput]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.id, p.season, p.games, p.minutes,
                   p.field_goals_attempted, p.free_throws_attempted,
                   e.shot_range,
                   COUNT(*)::int AS attempts,
                   COUNT(*) FILTER (WHERE e.made)::int AS makes,
                   COUNT(*) FILTER (
                       WHERE e.shot_range IN ('jumper', 'three_pointer') AND e.made
                   )::int AS perimeter_makes,
                   COUNT(*) FILTER (
                       WHERE e.shot_range IN ('jumper', 'three_pointer')
                         AND e.made AND e.assisted
                   )::int AS assisted_perimeter_makes
            FROM players p
            JOIN player_shot_events e
              ON e.player_id = p.id AND e.season = p.season
            WHERE p.season BETWEEN %s AND %s
              AND p.minutes > 0
              AND e.shot_range = ANY(%s)
              AND EXISTS (
                  SELECT 1
                  FROM player_shooting_ingestion_status status
                  WHERE status.player_id = p.id
                    AND status.season = p.season
                    AND (
                        status.status = 'success'
                        OR (status.status = 'failed' AND status.event_count > 0)
                    )
              )
            GROUP BY p.id, p.season, p.games, p.minutes,
                     p.field_goals_attempted, p.free_throws_attempted,
                     e.shot_range
            ORDER BY p.season, p.id, e.shot_range
            """,
            (first, last, list(ZONES)),
        )
        rows = cursor.fetchall()

    grouped: dict[tuple[int, int], dict] = {}
    for row in rows:
        (
            player_id, season, games, minutes, box_fga, box_fta, zone,
            attempts, makes, perimeter_makes, assisted_perimeter_makes,
        ) = row
        item = grouped.setdefault(
            (player_id, season),
            {
                "player_id": player_id,
                "season": season,
                "games": games,
                "minutes": minutes,
                "box_fga": box_fga,
                "box_fta": box_fta,
                "zones": {},
                "perimeter_makes": 0,
                "assisted_perimeter_makes": 0,
            },
        )
        item["zones"][zone] = ZoneCount(attempts, makes)
        item["perimeter_makes"] += perimeter_makes
        item["assisted_perimeter_makes"] += assisted_perimeter_makes
    return [PlayerShootingInput(**item) for item in grouped.values()]


def validate_source(conn: Any, first: int, last: int) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT shot_range, COUNT(*)
            FROM player_shot_events
            WHERE season BETWEEN %s AND %s
              AND (shot_range IS NULL OR NOT (shot_range = ANY(%s)))
            GROUP BY shot_range
            """,
            (first, last, list(ZONES)),
        )
        unknown = cursor.fetchall()
    if unknown:
        raise ValueError(f"Unknown or null shot ranges: {unknown}")


def source_checksum(conn: Any, first: int, last: int) -> str:
    digest = hashlib.sha256()
    with conn.cursor(name=f"shooting_source_checksum_{first}_{last}") as cursor:
        cursor.itersize = 1000
        cursor.execute(
            """
            SELECT source_play_id, raw_payload::text
            FROM player_shot_events
            WHERE season BETWEEN %s AND %s
            ORDER BY source_play_id
            """,
            (first, last),
        )
        for source_play_id, raw_payload in cursor:
            digest.update(str(source_play_id).encode())
            digest.update(b"\0")
            digest.update(raw_payload.encode())
            digest.update(b"\n")
    return digest.hexdigest()


def persist_profiles(
    conn: Any,
    profiles: list[dict],
    first: int,
    last: int,
    version: str,
) -> None:
    profile_records = [
        tuple(profile[column] if column != "model_version" else version for column in PROFILE_COLUMNS)
        for profile in profiles
    ]
    zone_records = []
    for profile in profiles:
        for zone in profile["zones"]:
            values = {
                **zone,
                "player_id": profile["player_id"],
                "season": profile["season"],
                "model_version": version,
            }
            zone_records.append(tuple(values[column] for column in ZONE_COLUMNS))

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO shooting_model_versions (version, is_active, configuration)
            VALUES (%s, FALSE, %s)
            """,
            (version, Json(MODEL_CONFIGURATION)),
        )
        cursor.execute(
            """
            DELETE FROM player_shooting_ability_profiles
            WHERE model_version = %s AND season BETWEEN %s AND %s
            """,
            (version, first, last),
        )
        execute_values(
            cursor,
            f"INSERT INTO player_shooting_ability_profiles ({', '.join(PROFILE_COLUMNS)}) VALUES %s",
            profile_records,
            page_size=500,
        )
        execute_values(
            cursor,
            f"INSERT INTO player_shooting_zone_profiles ({', '.join(ZONE_COLUMNS)}) VALUES %s",
            zone_records,
            page_size=1000,
        )


def quality_summary(conn: Any, version: str) -> tuple[int, int, int, int]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)::int,
                   COUNT(*) FILTER (WHERE zone_count = 4)::int,
                   COUNT(*) FILTER (WHERE event_coverage < 0.90)::int,
                   COALESCE(SUM(zone_count), 0)::int
            FROM (
                SELECT profile.player_id, profile.season, profile.event_coverage,
                       COUNT(zone.zone)::int AS zone_count
                FROM player_shooting_ability_profiles profile
                LEFT JOIN player_shooting_zone_profiles zone
                  ON zone.player_id = profile.player_id
                 AND zone.season = profile.season
                 AND zone.model_version = profile.model_version
                WHERE profile.model_version = %s
                GROUP BY profile.player_id, profile.season, profile.event_coverage
            ) profiles
            """,
            (version,),
        )
        return cursor.fetchone()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=int, default=FIRST_SEASON)
    parser.add_argument("--last", type=int, default=LAST_SEASON)
    parser.add_argument("--version", default=MODEL_VERSION)
    parser.add_argument("--draws", type=int, default=10_000)
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
        validate_source(conn, args.first, args.last)
        checksum = source_checksum(conn, args.first, args.last)
        commit = pipeline_commit(REPO_ROOT)
        run_id = begin_import_run(
            conn,
            dataset="shooting_model",
            import_version=args.version,
            commit=commit,
            source_uri=(
                "postgres://player_shot_events"
                f"?first_season={args.first}&last_season={args.last}"
            ),
            first_season=args.first,
            last_season=args.last,
            model_version=args.version,
            metadata={"draws": args.draws, "configuration": MODEL_CONFIGURATION},
        )
        inputs = load_inputs(conn, args.first, args.last)
        profiles = build_ability_profiles(
            inputs,
            draws=args.draws,
            model_version=args.version,
        )
        if not profiles:
            raise ValueError("No usable shooting profiles were produced")
        persist_profiles(conn, profiles, args.first, args.last, args.version)
        total, complete_zones, low_coverage, zone_total = quality_summary(
            conn, args.version
        )
        if complete_zones != total:
            raise ValueError(
                f"Candidate {args.version} has {complete_zones}/{total} complete zones"
            )
        update_running_import(
            conn,
            run_id,
            source_sha256=checksum,
            staged_row_counts={
                "ability_profiles": total,
                "zone_profiles": zone_total,
            },
            validation_results={
                "ability_profiles": total,
                "profiles_with_four_zones": complete_zones,
                "profiles_below_90_percent_event_coverage": low_coverage,
            },
        )
    except Exception as error:
        if run_id is not None:
            mark_failed(conn, run_id, error)
        else:
            conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Stored inactive candidate {args.version}: {total:,} profiles")
    print(f"Profiles with four zones: {complete_zones:,}/{total:,}")
    print(f"Profiles below 90% event coverage: {low_coverage:,}/{total:,}")
    print("Run compute_contextual_shooting_signals.py to validate and activate it.")


if __name__ == "__main__":
    main()
