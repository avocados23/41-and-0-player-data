"""Ingest raw CBBD shooting plays for players already in PostgreSQL.

Examples:
    python ingest_cbbd_shots.py
    python ingest_cbbd_shots.py --player-id 2246 --refresh
    python ingest_cbbd_shots.py --first 2020 --last 2026 \
        --export shot_exports/shots_2020_2026.jsonl.gz

The job is resumable by default: player-seasons whose latest fetch succeeded or
returned no data are skipped. Use --refresh to fetch them again. A successful
response is treated as a full snapshot for that player-season, so upstream
corrections and removals are reconciled; a failed request never removes data.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import random
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import cbbd
import psycopg2
from cbbd.rest import ApiException
from psycopg2.extras import Json, execute_values

from process_torvik_defensive_data import connection_dsn, load_env_file
from shooting_data import EVENT_DB_COLUMNS, event_record, normalize_play


FIRST_SEASON = 2020
LAST_SEASON = 2026
DEFAULT_WORKERS = 4
DEFAULT_RETRIES = 4
EXPORT_COLUMNS = EVENT_DB_COLUMNS + ("created_at", "updated_at")

_thread_local = threading.local()


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def model_payload(play: Any) -> dict[str, Any]:
    """Convert generated CBBD models to alias-keyed, JSON-safe dictionaries."""
    if hasattr(play, "to_json"):
        try:
            return json.loads(play.to_json())
        except (TypeError, ValueError):
            # cbbd 1.27.3's generated to_json() does not encode datetimes.
            pass
    if hasattr(play, "json"):
        try:
            return json.loads(play.json(by_alias=True))
        except TypeError:
            return json.loads(play.json())
    value = play.to_dict() if hasattr(play, "to_dict") else play
    return json.loads(json.dumps(value, default=_json_default))


def _plays_api(access_token: str) -> Any:
    api = getattr(_thread_local, "plays_api", None)
    if api is None:
        configuration = cbbd.Configuration(access_token=access_token)
        client = cbbd.ApiClient(configuration)
        _thread_local.api_client = client
        api = cbbd.PlaysApi(client)
        _thread_local.plays_api = api
    return api


def _retryable(error: Exception) -> bool:
    if not isinstance(error, ApiException):
        return True
    if "monthly call quota exceeded" in str(error).lower():
        return False
    status = getattr(error, "status", None)
    return status == 429 or status is None or status >= 500


def fetch_player_season(
    access_token: str,
    player_id: int,
    season: int,
    max_retries: int = DEFAULT_RETRIES,
) -> list[dict[str, Any]]:
    """Fetch and normalize one complete player-season with bounded retries."""
    plays = None
    for attempt in range(1, max_retries + 1):
        try:
            plays = _plays_api(access_token).get_plays_by_player_id(
                player_id=player_id,
                season=season,
                shooting_plays_only=True,
                _request_timeout=(5, 30),
            )
            break
        except Exception as error:
            if attempt == max_retries or not _retryable(error):
                raise
            delay = min(30.0, 2 ** (attempt - 1)) + random.random()
            time.sleep(delay)

    # Normalize outside the retry block: malformed payloads are deterministic,
    # not transient API failures. Deduplicate defensively before bulk upsert.
    by_id = {}
    for play in plays or []:
        event = normalize_play(model_payload(play), player_id, season)
        by_id[event["source_play_id"]] = event
    return list(by_id.values())


def select_players(
    conn: Any, first: int, last: int, player_id: int | None
) -> list[tuple[int, int]]:
    params: list[Any] = [first, last]
    where = "p.season BETWEEN %s AND %s"
    if player_id is not None:
        where += " AND p.id = %s"
        params.append(player_id)
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT p.id, p.season
            FROM players p
            WHERE {where}
            ORDER BY p.season, p.id
            """,
            params,
        )
        return cursor.fetchall()


def completed_player_seasons(conn: Any) -> set[tuple[int, int]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT player_id, season
            FROM player_shooting_ingestion_status
            WHERE status IN ('success', 'no_data')
            """
        )
        return set(cursor.fetchall())


def sync_player_events(
    conn: Any, player_id: int, season: int, events: list[dict[str, Any]]
) -> None:
    """Atomically upsert and reconcile a successful full player-season response."""
    columns = ", ".join(EVENT_DB_COLUMNS)
    updates = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in EVENT_DB_COLUMNS
        if column not in ("source_play_id", "created_at")
    )
    records = []
    for event in events:
        values = list(event_record(event))
        values[EVENT_DB_COLUMNS.index("raw_payload")] = Json(event["raw_payload"])
        records.append(tuple(values))

    status = "success" if events else "no_data"
    with conn.cursor() as cursor:
        if records:
            execute_values(
                cursor,
                f"""
                INSERT INTO player_shot_events ({columns}) VALUES %s
                ON CONFLICT (source_play_id) DO UPDATE SET
                    {updates}, updated_at = now()
                """,
                records,
                page_size=500,
            )

        seen_ids = [event["source_play_id"] for event in events]
        if seen_ids:
            cursor.execute(
                """
                DELETE FROM player_shot_events
                WHERE player_id = %s AND season = %s
                  AND NOT (source_play_id = ANY(%s))
                """,
                (player_id, season, seen_ids),
            )
        else:
            cursor.execute(
                "DELETE FROM player_shot_events WHERE player_id = %s AND season = %s",
                (player_id, season),
            )

        cursor.execute(
            """
            INSERT INTO player_shooting_ingestion_status
                (player_id, season, status, event_count, error_message)
            VALUES (%s, %s, %s, %s, NULL)
            ON CONFLICT (player_id, season) DO UPDATE SET
                status = EXCLUDED.status,
                event_count = EXCLUDED.event_count,
                attempt_count = player_shooting_ingestion_status.attempt_count + 1,
                error_message = NULL,
                fetched_at = now()
            """,
            (player_id, season, status, len(events)),
        )
    conn.commit()


def record_failure(conn: Any, player_id: int, season: int, error: Exception) -> None:
    message = f"{type(error).__name__}: {error}"[:4000]
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO player_shooting_ingestion_status
                (player_id, season, status, event_count, error_message)
            VALUES (%s, %s, 'failed', 0, %s)
            ON CONFLICT (player_id, season) DO UPDATE SET
                status = 'failed',
                attempt_count = player_shooting_ingestion_status.attempt_count + 1,
                error_message = EXCLUDED.error_message,
                fetched_at = now()
            """,
            (player_id, season, message),
        )
    conn.commit()


def _open_export(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "wt", encoding="utf-8", newline="")
    return path.open("w", encoding="utf-8", newline="")


def export_events(
    conn: Any, destination: Path, first: int, last: int, file_format: str
) -> int:
    """Stream a deterministic JSONL or CSV snapshot from PostgreSQL."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.",
        suffix=destination.suffix,
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    count = 0
    try:
        with conn.cursor(name="shot_export") as cursor:
            cursor.itersize = 2000
            cursor.execute(
                f"""
                SELECT {', '.join(EXPORT_COLUMNS)}
                FROM player_shot_events
                WHERE season BETWEEN %s AND %s
                ORDER BY season, player_id, game_start_date NULLS LAST, game_id,
                         source_play_id
                """,
                (first, last),
            )
            with _open_export(temporary) as output:
                writer = None
                if file_format == "csv":
                    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS)
                    writer.writeheader()
                for values in cursor:
                    row = dict(zip(EXPORT_COLUMNS, values))
                    if file_format == "jsonl":
                        output.write(json.dumps(row, default=_json_default) + "\n")
                    else:
                        row["raw_payload"] = json.dumps(
                            row["raw_payload"],
                            default=_json_default,
                            separators=(",", ":"),
                        )
                        writer.writerow(row)
                    count += 1
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return count


def infer_export_format(path: Path, requested: str | None) -> str:
    if requested:
        return requested
    name = path.name.removesuffix(".gz")
    return "csv" if name.endswith(".csv") else "jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=int, default=FIRST_SEASON)
    parser.add_argument("--last", type=int, default=LAST_SEASON)
    parser.add_argument("--player-id", type=int)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument(
        "--refresh", action="store_true", help="refetch successful/empty player-seasons"
    )
    parser.add_argument("--export", type=Path)
    parser.add_argument("--format", choices=("jsonl", "csv"))
    parser.add_argument(
        "--skip-score", action="store_true", help="do not recompute affected seasons"
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
        candidates = select_players(conn, args.first, args.last, args.player_id)
        if args.player_id is not None and not candidates:
            raise SystemExit(
                f"Player {args.player_id} is not in the database for seasons "
                f"{args.first}-{args.last}"
            )
        if not args.refresh:
            complete = completed_player_seasons(conn)
            candidates = [item for item in candidates if item not in complete]
        print(f"Fetching {len(candidates)} player-seasons with {args.workers} workers")

        succeeded = failed = events_written = 0
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            candidate_iterator = iter(candidates)
            futures = {}

            def submit_next() -> bool:
                try:
                    player_id, season = next(candidate_iterator)
                except StopIteration:
                    return False
                future = executor.submit(
                    fetch_player_season,
                    access_token,
                    player_id,
                    season,
                    args.max_retries,
                )
                futures[future] = (player_id, season)
                return True

            for _ in range(args.workers):
                if not submit_next():
                    break

            index = 0
            while futures:
                future = next(as_completed(futures))
                index += 1
                player_id, season = futures[future]
                del futures[future]
                try:
                    events = future.result()
                    sync_player_events(conn, player_id, season, events)
                    succeeded += 1
                    events_written += len(events)
                except Exception as error:
                    conn.rollback()
                    record_failure(conn, player_id, season, error)
                    failed += 1
                    print(f"ERROR player={player_id} season={season}: {error}")
                submit_next()
                if index % 50 == 0 or index == len(candidates):
                    print(
                        f"Progress {index}/{len(candidates)}; success={succeeded}, "
                        f"failed={failed}, events={events_written}"
                    )

        if failed:
            raise SystemExit(
                f"{failed} player-season fetches failed; rerun to resume before "
                "publishing scores or exports"
            )

        if not args.skip_score:
            from compute_shooter_signals import recompute_shooter_profiles

            profile_count = recompute_shooter_profiles(conn, args.first, args.last)
            print(f"Recomputed {profile_count} shooting profiles")

        if args.export:
            file_format = infer_export_format(args.export, args.format)
            exported = export_events(
                conn, args.export, args.first, args.last, file_format
            )
            print(f"Exported {exported} events to {args.export}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
