"""Null out players.player_headshot_img for URLs ESPN's CDN 404s on.

populate_img_urls.py constructs a headshot URL for every player with an
athlete_source_id, but ESPN only has a photo for a subset of D1 players
(older/lower-profile athletes were often never photographed). This checks
every stored URL and clears the ones the CDN definitively 404s, so the column
only ever holds a URL that actually serves an image.

Each worker thread keeps one persistent HTTPS connection to the CDN (rebuilt
on error) instead of a fresh TLS handshake per request, and a URL is only
cleared on an unambiguous 404 -- transient network errors leave the row alone
and are reported at the end, so a flaky run can't wipe valid URLs.

Run after populate_img_urls.py:
    python -m scripts.ingest.validate_headshot_urls
"""

import http.client
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import execute_values

from bracketballer_data.database import connection_dsn, load_env_file

MAX_WORKERS = 20
TIMEOUT_SECONDS = 5
PROGRESS_EVERY = 1000

_local = threading.local()


def _connection(host):
    """Return this thread's persistent CDN connection, creating it if needed."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = http.client.HTTPSConnection(host, timeout=TIMEOUT_SECONDS)
        _local.conn = conn
    return conn


def _drop_connection():
    """Close and discard this thread's connection so the next call rebuilds it."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def check_url(url):
    """Return 'ok', 'dead', or 'error' for a headshot URL.

    'dead' means the CDN answered with a 4xx -- the image definitively does not
    exist. 'error' covers timeouts/resets/5xx, where we can't conclude anything.
    """
    parts = urlsplit(url)
    for attempt in range(2):
        try:
            conn = _connection(parts.netloc)
            conn.request("HEAD", parts.path)
            response = conn.getresponse()
            response.read()
            if response.status == 200:
                return "ok"
            if 400 <= response.status < 500:
                return "dead"
            _drop_connection()
        except (OSError, http.client.HTTPException):
            _drop_connection()
    return "error"


def main():
    load_env_file()
    dsn = connection_dsn()

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, player_headshot_img FROM players "
            "WHERE player_headshot_img IS NOT NULL"
        )
        rows = cur.fetchall()

    dead_ids, error_count, done = [], 0, 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(check_url, url): player_id for player_id, url in rows
        }
        for future in as_completed(futures):
            result = future.result()
            if result == "dead":
                dead_ids.append(futures[future])
            elif result == "error":
                error_count += 1
            done += 1
            if done % PROGRESS_EVERY == 0:
                print(
                    f"checked {done}/{len(rows)} "
                    f"(dead so far: {len(dead_ids)}, errors: {error_count})",
                    flush=True,
                )

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        execute_values(
            cur,
            "UPDATE players p SET player_headshot_img = NULL "
            "FROM (VALUES %s) AS v(player_id) WHERE p.id = v.player_id",
            [(player_id,) for player_id in dead_ids],
            template="(%s)",
            page_size=500,
        )
    conn.close()

    print(f"Checked:  {len(rows)}")
    print(f"Cleared:  {len(dead_ids)} (definitive 404s, set to NULL)")
    print(f"Kept:     {len(rows) - len(dead_ids) - error_count}")
    print(f"Errors:   {error_count} (left untouched; rerun to retry)")


if __name__ == "__main__":
    main()
