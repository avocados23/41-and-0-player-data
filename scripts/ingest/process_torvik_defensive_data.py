"""Ingest Bart Torvik player advanced (defensive) stats into player_defensive_stats.

The existing players table was sourced from the CBBD API and its defensive
columns (defensive_rating, net_rating) are corrupted. This script re-sources
clean defensive stats from Bart Torvik's bulk player advanced feed, one season
at a time, caches each season's raw CSV locally, and upserts the columns we care
about into the player_defensive_stats landing table.

Torvik asks that the site not be hammered, so responses are cached on disk and
requests are rate-limited; a cached season is reused unless --refresh is passed.

DB connection comes from the environment (same vars as .env): PSQL_USER,
PSQL_PWD, DEV_DB (host/port default to localhost:5432, override with PSQL_HOST /
PSQL_PORT). A full DATABASE_URL (e.g. the Neon connection string) takes
precedence if set.

Run from the project root, after the V10 migration has created the table:
    python -m scripts.ingest.process_torvik_defensive_data
    python -m scripts.ingest.process_torvik_defensive_data --refresh
    python -m scripts.ingest.process_torvik_defensive_data --first 2020 --last 2025
"""

import argparse
import time
import urllib.request

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

# 2008 is the first Torvik season with full advanced coverage; 2026 is the
# latest completed season (2025-26). Pre-2008 players keep null defensive stats.
FIRST_SEASON = 2008
LAST_SEASON = 2026

from bracketballer_data.database import connection_dsn, load_env_file
from bracketballer_data.paths import TORVIK_CACHE

CACHE_DIR = TORVIK_CACHE
# Bart's bulk advanced player feed. csv=1 returns a headerless CSV, one row per
# player-season. The columns are positional (see TORVIK_COLUMNS below).
ENDPOINT = "https://barttorvik.com/getadvstats.php?year={year}&csv=1"
# Be a polite client: identify ourselves and pause between season downloads.
USER_AGENT = "casketball-defensive-ingest/1.0 (+contact: casketball)"
REQUEST_DELAY_SECONDS = 3.0

# Torvik's getadvstats.php CSV has no header. These are the zero-based column
# positions we pull; the layout is stable across 2008-2025 (verified against
# multiple seasons). Only columns we need are listed -- the rest (shot-location
# splits, offensive box scores, dob, etc.) are ignored.
TORVIK_COLUMNS = {
    "player": 0,    # player name
    "team": 1,      # school name (Torvik spelling)
    "conf": 2,      # conference
    "g": 3,         # games played
    "dr_pct": 10,   # defensive rebound rate (DRB%)
    "blk_pct": 22,  # block rate (BLK%)
    "stl_pct": 23,  # steal rate (STL%)
    "year": 31,     # season ending year, e.g. 2023
    "torvik_id": 32,  # Torvik player id (join key)
    "drtg": 46,     # defensive rating (sanity check only)
    "dporpag": 48,  # defensive PORPAG (primary defensive anchor)
    "dbpm": 52,     # defensive box plus/minus (secondary anchor)
}

# Final column order written to the DB (matches player_defensive_stats).
DB_COLUMNS = [
    "torvik_id",
    "player",
    "team",
    "conf",
    "season",
    "games",
    "dporpag",
    "dbpm",
    "drtg",
    "blk_pct",
    "stl_pct",
    "dr_pct",
]

INTEGER_COLUMNS = ("torvik_id", "season", "games")
FLOAT_COLUMNS = ("dporpag", "dbpm", "drtg", "blk_pct", "stl_pct", "dr_pct")


def download_season(year, refresh=False):
    """Return the local cache path for a season's raw CSV, downloading if needed."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"adv_{year}.csv"
    if path.exists() and not refresh:
        print(f"{year}: using cached {path}")
        return path

    url = ENDPOINT.format(year=year)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    path.write_bytes(body)
    print(f"{year}: downloaded {len(body):,} bytes -> {path}")
    # Rate-limit only when we actually hit the network.
    time.sleep(REQUEST_DELAY_SECONDS)
    return path


def parse_season(path):
    """Parse a cached season CSV into a tidy DataFrame with DB_COLUMNS."""
    positions = sorted(TORVIK_COLUMNS.values())
    raw = pd.read_csv(path, header=None, usecols=positions)

    # Map the positional columns to names. usecols keeps source order, so
    # rebuild the index->name lookup against the columns pandas actually kept.
    index_to_name = {idx: name for name, idx in TORVIK_COLUMNS.items()}
    raw.columns = [index_to_name[idx] for idx in raw.columns]

    # "year" is Torvik's season ending year, which is exactly our season key.
    raw = raw.rename(columns={"year": "season", "g": "games"})

    for col in INTEGER_COLUMNS:
        raw[col] = pd.to_numeric(raw[col], errors="coerce").astype("Int64")
    for col in FLOAT_COLUMNS:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")

    raw["player"] = raw["player"].astype("string").str.strip()
    raw["team"] = raw["team"].astype("string").str.strip()
    raw["conf"] = raw["conf"].astype("string").str.strip()

    # Drop rows missing a join key -- they can't be matched or upserted.
    before = len(raw)
    raw = raw.dropna(subset=["torvik_id", "season", "player"])
    dropped = before - len(raw)
    if dropped:
        print(f"  dropped {dropped} rows missing torvik_id/season/player")

    return raw[DB_COLUMNS]


def upsert_rows(conn, df):
    """Upsert a season's rows into player_defensive_stats on (torvik_id, season)."""
    if df.empty:
        return 0

    # Convert to native Python objects for psycopg2: pandas NA/NaN -> None, and
    # numpy scalars (numpy.int64/float64) -> Python int/float via .item().
    def to_py(value):
        if pd.isna(value):
            return None
        return value.item() if hasattr(value, "item") else value

    records = [
        tuple(to_py(value) for value in row)
        for row in df.itertuples(index=False, name=None)
    ]

    columns = ", ".join(DB_COLUMNS)
    updatable = [c for c in DB_COLUMNS if c not in ("torvik_id", "season")]
    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in updatable)
    sql = (
        f"INSERT INTO player_defensive_stats ({columns}) VALUES %s "
        f"ON CONFLICT (torvik_id, season) DO UPDATE SET "
        f"{update_set}, updated_at = now()"
    )

    with conn.cursor() as cur:
        execute_values(cur, sql, records, page_size=500)
    return len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=int, default=FIRST_SEASON)
    parser.add_argument("--last", type=int, default=LAST_SEASON)
    parser.add_argument(
        "--refresh", action="store_true", help="re-download cached seasons"
    )
    args = parser.parse_args()

    load_env_file()
    conn = psycopg2.connect(connection_dsn())
    conn.autocommit = False
    total = 0
    try:
        for year in range(args.first, args.last + 1):
            path = download_season(year, refresh=args.refresh)
            df = parse_season(path)
            written = upsert_rows(conn, df)
            conn.commit()
            total += written
            print(f"{year}: upserted {written} player-seasons")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Done. Upserted {total} player-seasons into player_defensive_stats.")


if __name__ == "__main__":
    main()
