"""Compute season-relative shooter profiles from ingested CBBD shot events.

Run independently after ingestion when scoring weights or thresholds change:
    python compute_shooter_signals.py --first 2020 --last 2026
"""

from __future__ import annotations

import argparse
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

from process_torvik_defensive_data import connection_dsn, load_env_file
from shooting_data import ShootingAggregate, build_shooting_profiles


FIRST_SEASON = 2020
LAST_SEASON = 2026
PROFILE_COLUMNS = (
    "player_id",
    "season",
    "shooting_events",
    "field_goal_attempts",
    "free_throw_attempts",
    "three_point_attempts",
    "three_point_made",
    "raw_three_point_pct",
    "adjusted_three_point_pct",
    "three_point_attempts_pg",
    "three_point_attempt_share",
    "assisted_three_rate",
    "coordinate_coverage",
    "shooter_score",
    "is_shooter",
)


def load_aggregates(conn: Any, first: int, last: int) -> list[ShootingAggregate]:
    """Aggregate complete snapshots, retaining data after a failed refresh."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                p.id,
                p.season,
                p.games,
                COUNT(e.source_play_id) AS shooting_events,
                COUNT(e.source_play_id) FILTER (
                    WHERE e.shot_range <> 'free_throw'
                ) AS field_goal_attempts,
                COUNT(e.source_play_id) FILTER (
                    WHERE e.shot_range = 'free_throw'
                ) AS free_throw_attempts,
                COUNT(e.source_play_id) FILTER (
                    WHERE e.shot_range = 'three_pointer'
                ) AS three_point_attempts,
                COUNT(e.source_play_id) FILTER (
                    WHERE e.shot_range = 'three_pointer' AND e.made
                ) AS three_point_made,
                COUNT(e.source_play_id) FILTER (
                    WHERE e.shot_range = 'three_pointer' AND e.made AND e.assisted
                ) AS assisted_three_made,
                COUNT(e.source_play_id) FILTER (
                    WHERE e.shot_range <> 'free_throw'
                      AND e.location_x IS NOT NULL AND e.location_y IS NOT NULL
                ) AS coordinate_field_goal_attempts
            FROM player_shooting_ingestion_status status
            JOIN players p
              ON p.id = status.player_id AND p.season = status.season
            JOIN player_shot_events e
              ON e.player_id = status.player_id AND e.season = status.season
            WHERE (
                    status.status = 'success'
                    OR (status.status = 'failed' AND status.event_count > 0)
                  )
              AND p.season BETWEEN %s AND %s
            GROUP BY p.id, p.season, p.games
            ORDER BY p.season, p.id
            """,
            (first, last),
        )
        return [ShootingAggregate(*row) for row in cursor.fetchall()]


def recompute_shooter_profiles(conn: Any, first: int, last: int) -> int:
    """Replace profiles and mirrored player signals for complete seasons in range."""
    aggregates = load_aggregates(conn, first, last)
    profiles = build_shooting_profiles(aggregates)
    records = [tuple(profile[column] for column in PROFILE_COLUMNS) for profile in profiles]

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM player_shooting_profiles WHERE season BETWEEN %s AND %s",
                (first, last),
            )
            cursor.execute(
                """
                UPDATE players
                SET shooter_score = NULL, is_shooter = NULL
                WHERE season BETWEEN %s AND %s
                """,
                (first, last),
            )
            if records:
                execute_values(
                    cursor,
                    f"""
                    INSERT INTO player_shooting_profiles ({', '.join(PROFILE_COLUMNS)})
                    VALUES %s
                    """,
                    records,
                    page_size=500,
                )
                cursor.execute(
                    """
                    UPDATE players p
                    SET shooter_score = profile.shooter_score,
                        is_shooter = profile.is_shooter
                    FROM player_shooting_profiles profile
                    WHERE p.id = profile.player_id
                      AND p.season = profile.season
                      AND profile.season BETWEEN %s AND %s
                    """,
                    (first, last),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(profiles)


def quality_summary(conn: Any, first: int, last: int) -> tuple[int, int, int]:
    """Return profile, shooter, and material raw-vs-box-score mismatch counts."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                COUNT(*),
                COUNT(*) FILTER (WHERE profile.is_shooter),
                COUNT(*) FILTER (
                    WHERE ABS(profile.three_point_attempts - p.three_point_field_goals_attempted)
                          > GREATEST(5, p.three_point_field_goals_attempted * 0.10)
                )
            FROM player_shooting_profiles profile
            JOIN players p ON p.id = profile.player_id AND p.season = profile.season
            WHERE profile.season BETWEEN %s AND %s
            """,
            (first, last),
        )
        return cursor.fetchone()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=int, default=FIRST_SEASON)
    parser.add_argument("--last", type=int, default=LAST_SEASON)
    args = parser.parse_args()
    if args.first > args.last:
        parser.error("--first cannot be greater than --last")

    load_env_file()
    conn = psycopg2.connect(connection_dsn())
    conn.autocommit = False
    try:
        count = recompute_shooter_profiles(conn, args.first, args.last)
        profiles, shooters, mismatches = quality_summary(conn, args.first, args.last)
    finally:
        conn.close()
    print(f"Computed {count} profiles ({shooters} shooters)")
    print(f"Raw-vs-box-score 3PA mismatches over 10% (and >5 attempts): {mismatches}/{profiles}")


if __name__ == "__main__":
    main()
