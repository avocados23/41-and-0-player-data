"""Helpers for durable, versioned data-import audit records."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def pipeline_commit(repo: Path) -> str:
    configured = os.environ.get("PIPELINE_COMMIT", "").strip().lower()
    if configured:
        commit = configured
    else:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip().lower()
    if not 7 <= len(commit) <= 64 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("PIPELINE_COMMIT must be a 7-64 character hexadecimal commit")
    return commit


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def begin_import_run(
    conn: Any,
    *,
    dataset: str,
    import_version: str,
    commit: str,
    source_uri: str,
    first_season: int,
    last_season: int,
    model_version: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO data_import_runs (
                dataset, import_version, pipeline_commit, source_uri,
                first_season, last_season, model_version, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                dataset,
                import_version,
                commit,
                source_uri,
                first_season,
                last_season,
                model_version,
                _json(metadata or {}),
            ),
        )
        run_id = cursor.fetchone()[0]
    conn.commit()
    return run_id


def mark_validated(
    conn: Any,
    run_id: int,
    *,
    source_sha256: str,
    staged_row_counts: dict[str, int],
    validation_results: dict[str, Any],
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE data_import_runs
            SET status = 'validated',
                source_sha256 = %s,
                staged_row_counts = %s::jsonb,
                validation_results = %s::jsonb,
                validated_at = now()
            WHERE id = %s AND status = 'running'
            """,
            (
                source_sha256,
                _json(staged_row_counts),
                _json(validation_results),
                run_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Import run {run_id} is not running")
    conn.commit()


def update_running_import(
    conn: Any,
    run_id: int,
    *,
    source_sha256: str,
    staged_row_counts: dict[str, int],
    validation_results: dict[str, Any],
) -> None:
    """Record candidate output while leaving it unavailable for publication."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE data_import_runs
            SET source_sha256 = %s,
                staged_row_counts = %s::jsonb,
                validation_results = %s::jsonb
            WHERE id = %s AND status = 'running'
            """,
            (
                source_sha256,
                _json(staged_row_counts),
                _json(validation_results),
                run_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Import run {run_id} is not running")
    conn.commit()


def mark_failed(conn: Any, run_id: int, error: Exception) -> None:
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE data_import_runs
            SET status = 'failed', error_message = %s, finished_at = now()
            WHERE id = %s AND status IN ('running', 'validated')
            """,
            (str(error)[:4000], run_id),
        )
    conn.commit()
