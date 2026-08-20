"""Bulk-ingest raw CBBD shooting plays by game date.

This is the preferred historical backfill path. It discovers actual game dates
with one Games API request per season, fetches all shooting plays once per date,
and filters them to player ids present in PostgreSQL. Each season is staged in a
temporary PostgreSQL table and published atomically only after every date has
succeeded, so a failed API request cannot expose a partial season.

Examples:
    python -m scripts.ingest.ingest_cbbd_shots_bulk --first 2020 --last 2026
    python -m scripts.ingest.ingest_cbbd_shots_bulk --first 2026 --last 2026 --refresh
    python -m scripts.ingest.ingest_cbbd_shots_bulk --export data/exports/shots/shots.jsonl.gz
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import cbbd
import psycopg2
from cbbd.rest import ApiException
from psycopg2.extras import Json, execute_values

from bracketballer_data.database import connection_dsn, load_env_file
from bracketballer_data.import_audit import (
    begin_import_run,
    mark_failed,
    mark_validated,
    pipeline_commit,
)
from bracketballer_data.shooting_data import (
    EVENT_DB_COLUMNS,
    event_record,
    normalize_eligible_plays,
)
from bracketballer_data.paths import REPO_ROOT
from scripts.compute.compute_shooter_signals import recompute_shooter_profiles
from scripts.ingest.ingest_cbbd_shots import export_events, infer_export_format, model_payload


FIRST_SEASON = 2020
LAST_SEASON = 2026
DEFAULT_WORKERS = 2
DEFAULT_RETRIES = 4
GAME_CALENDAR_WINDOW_DAYS = 14
STAGE_TABLE = "player_shot_events_bulk_stage"

_thread_local = threading.local()


def _apis(access_token: str) -> tuple[Any, Any]:
    games_api = getattr(_thread_local, "games_api", None)
    plays_api = getattr(_thread_local, "plays_api", None)
    if games_api is None or plays_api is None:
        configuration = cbbd.Configuration(access_token=access_token)
        client = cbbd.ApiClient(configuration)
        _thread_local.api_client = client
        games_api = cbbd.GamesApi(client)
        plays_api = cbbd.PlaysApi(client)
        _thread_local.games_api = games_api
        _thread_local.plays_api = plays_api
    return games_api, plays_api


def _retryable(error: Exception) -> bool:
    if not isinstance(error, ApiException):
        return True
    if "monthly call quota exceeded" in str(error).lower():
        return False
    status = getattr(error, "status", None)
    return status == 429 or status is None or status >= 500


def call_with_retries(call: Callable[[], Any], max_retries: int) -> Any:
    for attempt in range(1, max_retries + 1):
        try:
            return call()
        except Exception as error:
            if attempt == max_retries or not _retryable(error):
                raise
            time.sleep(min(30.0, 2 ** (attempt - 1)) + random.random())
    raise AssertionError("retry loop exited unexpectedly")


def fetch_game_dates(
    access_token: str, season: int, max_retries: int
) -> list[date]:
    """Discover all game dates in bounded windows to avoid CBBD's 3,000-row cap."""
    games_api, _ = _apis(access_token)
    season_start = datetime(season - 1, 10, 1, tzinfo=timezone.utc)
    season_end = datetime(season, 5, 15, tzinfo=timezone.utc)
    game_dates: set[date] = set()
    window_start = season_start
    while window_start < season_end:
        window_end = min(
            season_end,
            window_start + timedelta(days=GAME_CALENDAR_WINDOW_DAYS),
        )
        games = call_with_retries(
            lambda start=window_start, end=window_end: games_api.get_games(
                season=season,
                start_date_range=start,
                end_date_range=end,
                _request_timeout=(10, 120),
            ),
            max_retries,
        )
        game_dates.update(game.start_date.date() for game in games or [])
        window_start = window_end
    return sorted(game_dates)


def fetch_date_plays(
    access_token: str,
    game_date: date,
    eligible_player_ids: set[int],
    season: int,
    max_retries: int,
) -> list[dict[str, Any]]:
    _, plays_api = _apis(access_token)
    query_date = datetime.combine(game_date, datetime_time.min, timezone.utc)
    plays = call_with_retries(
        lambda: plays_api.get_plays_by_date(
            var_date=query_date,
            shooting_plays_only=True,
            _request_timeout=(10, 120),
        ),
        max_retries,
    )
    raw_plays = [model_payload(play) for play in plays or []]
    return normalize_eligible_plays(raw_plays, eligible_player_ids, season)


def eligible_players(conn: Any, season: int) -> set[int]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM players WHERE season = %s", (season,))
        return {row[0] for row in cursor.fetchall()}


def season_is_complete(conn: Any, season: int) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                COUNT(*) AS players,
                COUNT(status.player_id) FILTER (
                    WHERE status.status IN ('success', 'no_data')
                ) AS completed
            FROM players p
            LEFT JOIN player_shooting_ingestion_status status
              ON status.player_id = p.id AND status.season = p.season
            WHERE p.season = %s
            """,
            (season,),
        )
        players, completed = cursor.fetchone()
        return players > 0 and players == completed


def prepare_stage(conn: Any) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TEMP TABLE IF NOT EXISTS {STAGE_TABLE}
                (LIKE player_shot_events INCLUDING ALL)
                ON COMMIT PRESERVE ROWS
            """
        )
        cursor.execute(f"TRUNCATE {STAGE_TABLE}")
    conn.commit()


def stage_events(conn: Any, events: list[dict[str, Any]]) -> int:
    if not events:
        return 0
    columns = ", ".join(EVENT_DB_COLUMNS)
    updates = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in EVENT_DB_COLUMNS
        if column != "source_play_id"
    )
    raw_index = EVENT_DB_COLUMNS.index("raw_payload")
    records = []
    for event in events:
        values = list(event_record(event))
        values[raw_index] = Json(event["raw_payload"])
        records.append(tuple(values))
    with conn.cursor() as cursor:
        execute_values(
            cursor,
            f"""
            INSERT INTO {STAGE_TABLE} ({columns}) VALUES %s
            ON CONFLICT (source_play_id) DO UPDATE SET {updates}
            """,
            records,
            page_size=500,
        )
    conn.commit()
    return len(records)


def stage_checksum(conn: Any, season: int) -> str:
    digest = hashlib.sha256()
    with conn.cursor(name=f"shot_stage_checksum_{season}") as cursor:
        cursor.itersize = 1000
        cursor.execute(
            f"""
            SELECT source_play_id, raw_payload::text
            FROM {STAGE_TABLE}
            WHERE season = %s
            ORDER BY source_play_id
            """,
            (season,),
        )
        for source_play_id, raw_payload in cursor:
            digest.update(str(source_play_id).encode())
            digest.update(b"\0")
            digest.update(raw_payload.encode())
            digest.update(b"\n")
    return digest.hexdigest()


def validate_stage(conn: Any, season: int) -> dict[str, Any]:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                COUNT(*)::int,
                COUNT(DISTINCT stage.source_play_id)::int,
                COUNT(*) FILTER (WHERE stage.season <> %s)::int,
                COUNT(*) FILTER (WHERE player.id IS NULL)::int
            FROM {STAGE_TABLE} stage
            LEFT JOIN players player
              ON player.id = stage.player_id AND player.season = stage.season
            WHERE stage.season = %s OR stage.season <> %s
            """,
            (season, season, season),
        )
        staged, unique_ids, wrong_season, orphan_players = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*)::int FROM player_shot_events WHERE season = %s",
            (season,),
        )
        previous = cursor.fetchone()[0]

    lower_bound = int(previous * 0.5) if previous else 1
    upper_bound = int(previous * 1.5) if previous else None
    results = {
        "staged_rows": staged,
        "unique_source_play_ids": unique_ids,
        "wrong_season_rows": wrong_season,
        "orphan_player_rows": orphan_players,
        "previous_published_rows": previous,
        "minimum_expected_rows": lower_bound,
        "maximum_expected_rows": upper_bound,
    }
    if staged == 0:
        raise ValueError(f"Season {season} staged no shot events")
    if unique_ids != staged or wrong_season or orphan_players:
        raise ValueError(f"Season {season} failed stage integrity checks: {results}")
    if previous and not lower_bound <= staged <= upper_bound:
        raise ValueError(f"Season {season} failed row-count bounds: {results}")
    return results


def publish_season(conn: Any, season: int, run_id: int) -> int:
    """Atomically replace one season and mark every eligible player complete."""
    columns = ", ".join(EVENT_DB_COLUMNS)
    updates = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in EVENT_DB_COLUMNS
        if column != "source_play_id"
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM player_shot_events WHERE season = %s",
                (season,),
            )
            cursor.execute(
                f"""
                INSERT INTO player_shot_events ({columns})
                SELECT {columns} FROM {STAGE_TABLE}
                WHERE season = %s
                ON CONFLICT (source_play_id) DO UPDATE SET
                    {updates},
                    updated_at = now()
                """,
                (season,),
            )
            cursor.execute(
                """
                UPDATE data_import_runs
                SET status = 'published',
                    published_row_counts = jsonb_build_object(
                        'player_shot_events', %s::int
                    ),
                    published_at = now(),
                    finished_at = now()
                WHERE id = %s AND status = 'validated'
                """,
                (published, run_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Import run {run_id} is not validated")
            published = cursor.rowcount
            cursor.execute(
                f"""
                INSERT INTO player_shooting_ingestion_status
                    (player_id, season, status, event_count, error_message)
                SELECT
                    p.id,
                    p.season,
                    CASE WHEN COUNT(stage.source_play_id) > 0
                         THEN 'success' ELSE 'no_data' END,
                    COUNT(stage.source_play_id)::INTEGER,
                    NULL
                FROM players p
                LEFT JOIN {STAGE_TABLE} stage
                  ON stage.player_id = p.id AND stage.season = p.season
                WHERE p.season = %s
                GROUP BY p.id, p.season
                ON CONFLICT (player_id, season) DO UPDATE SET
                    status = EXCLUDED.status,
                    event_count = EXCLUDED.event_count,
                    attempt_count = player_shooting_ingestion_status.attempt_count + 1,
                    error_message = NULL,
                    fetched_at = now()
                """,
                (season,),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return published


def ingest_season(
    conn: Any,
    access_token: str,
    season: int,
    workers: int,
    max_retries: int,
    run_id: int,
) -> tuple[int, int]:
    player_ids = eligible_players(conn, season)
    if not player_ids:
        print(f"{season}: no database players; skipping")
        return 0, 0
    game_dates = fetch_game_dates(access_token, season, max_retries)
    if not game_dates:
        raise RuntimeError(f"CBBD returned no games for season {season}")

    prepare_stage(conn)
    staged = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        date_iterator = iter(game_dates)
        futures = {}

        def submit_next() -> bool:
            try:
                game_date = next(date_iterator)
            except StopIteration:
                return False
            future = executor.submit(
                fetch_date_plays,
                access_token,
                game_date,
                player_ids,
                season,
                max_retries,
            )
            futures[future] = game_date
            return True

        for _ in range(workers):
            if not submit_next():
                break

        completed = 0
        while futures:
            future = next(as_completed(futures))
            game_date = futures.pop(future)
            events = future.result()
            staged += stage_events(conn, events)
            completed += 1
            submit_next()
            if completed % 20 == 0 or completed == len(game_dates):
                print(
                    f"{season}: dates {completed}/{len(game_dates)}, "
                    f"staged events={staged:,} (latest {game_date})"
                )

    validation = validate_stage(conn, season)
    checksum = stage_checksum(conn, season)
    mark_validated(
        conn,
        run_id,
        source_sha256=checksum,
        staged_row_counts={"player_shot_events": validation["staged_rows"]},
        validation_results=validation,
    )
    published = publish_season(conn, season, run_id)
    return len(game_dates), published


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=int, default=FIRST_SEASON)
    parser.add_argument("--last", type=int, default=LAST_SEASON)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--export", type=Path)
    parser.add_argument("--format", choices=("jsonl", "csv"))
    parser.add_argument("--skip-score", action="store_true")
    parser.add_argument(
        "--release-version",
        help="Immutable release prefix; defaults to timestamp plus pipeline commit",
    )
    args = parser.parse_args()
    if args.first > args.last:
        parser.error("--first cannot be greater than --last")
    if args.workers < 1 or args.max_retries < 1:
        parser.error("--workers and --max-retries must be positive")

    load_env_file()
    access_token = os.environ.get("CBBD_API_KEY")
    if not access_token:
        raise SystemExit("Missing CBBD_API_KEY environment variable")

    conn = psycopg2.connect(connection_dsn())
    conn.autocommit = False
    try:
        commit = pipeline_commit(REPO_ROOT)
        release_version = args.release_version or (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + f"-{commit[:12]}"
        )
        total_dates = total_events = 0
        for season in range(args.first, args.last + 1):
            if not args.refresh and season_is_complete(conn, season):
                print(f"{season}: already complete; skipping")
                continue
            run_id = begin_import_run(
                conn,
                dataset="cbbd_player_shot_events",
                import_version=f"{release_version}-s{season}",
                commit=commit,
                source_uri=f"cbbd://plays?season={season}",
                first_season=season,
                last_season=season,
                metadata={"workers": args.workers, "max_retries": args.max_retries},
            )
            try:
                dates, events = ingest_season(
                    conn,
                    access_token,
                    season,
                    args.workers,
                    args.max_retries,
                    run_id,
                )
            except Exception as error:
                mark_failed(conn, run_id, error)
                raise
            total_dates += dates
            total_events += events
            print(f"{season}: published {events:,} events from {dates} dates")

        if not args.skip_score:
            profiles = recompute_shooter_profiles(conn, args.first, args.last)
            print(f"Recomputed {profiles:,} shooting profiles")
        if args.export:
            args.export.parent.mkdir(parents=True, exist_ok=True)
            file_format = infer_export_format(args.export, args.format)
            exported = export_events(
                conn, args.export, args.first, args.last, file_format
            )
            print(f"Exported {exported:,} events to {args.export}")
        print(
            f"Done. Published {total_events:,} events from "
            f"{total_dates} CBBD date responses."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
