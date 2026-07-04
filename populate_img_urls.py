"""Populate players.player_headshot_img and schools.school_logo_img.

Both columns hold ESPN CDN URLs, keyed by the ESPN ids that CBBD already
exposes as sourceId (players.athlete_source_id and TeamInfo.sourceId).
No ESPN scraping is involved -- schools are matched via a single CBBD
get_teams() call, and player headshot URLs are built straight from the
athlete_source_id column already sitting in the DB.

Schools that don't match any CBBD team (name spelling differences) are left
NULL and printed for manual review, the same way reconcile_torvik_ids.py
handles its unmatched rows.

Run from the project root:
    python populate_img_urls.py
"""

import os

import cbbd
import psycopg2
from psycopg2.extras import execute_values

from process_torvik_defensive_data import connection_dsn, load_env_file

HEADSHOT_URL_PREFIX = "https://a.espncdn.com/i/headshots/mens-college-basketball/players/full/"
LOGO_URL = "https://a.espncdn.com/i/teamlogos/ncaa/500/{}.png"


def fetch_team_source_ids():
    """Return {school_name: espn_source_id} via a single CBBD get_teams() call."""
    access_token = os.environ.get("CBBD_API_KEY")
    if not access_token:
        raise SystemExit(
            "Missing CBBD_API_KEY environment variable. "
            'Set it before running, e.g. export CBBD_API_KEY="<your token>"'
        )
    configuration = cbbd.Configuration(access_token=access_token)
    with cbbd.ApiClient(configuration) as api_client:
        teams = cbbd.TeamsApi(api_client).get_teams()
    return {team.school: team.source_id for team in teams}


def main():
    load_env_file()
    team_source_ids = fetch_team_source_ids()

    conn = psycopg2.connect(connection_dsn())
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM schools")
            schools = cur.fetchall()

            school_updates = []
            unmatched = []
            for school_id, name in schools:
                source_id = team_source_ids.get(name)
                if source_id is None:
                    unmatched.append(name)
                    continue
                school_updates.append((school_id, LOGO_URL.format(source_id)))

            execute_values(
                cur,
                """
                UPDATE schools s
                SET school_logo_img = v.logo_url
                FROM (VALUES %s) AS v(school_id, logo_url)
                WHERE s.id = v.school_id
                """,
                school_updates,
                template="(%s, %s)",
                page_size=500,
            )

            cur.execute(
                """
                UPDATE players
                SET player_headshot_img = %s || athlete_source_id || '.png'
                WHERE athlete_source_id IS NOT NULL
                """,
                (HEADSHOT_URL_PREFIX,),
            )
            players_updated = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Schools matched:   {len(school_updates)}/{len(schools)}")
    print(f"Players updated:   {players_updated}")
    if unmatched:
        print(f"Unmatched schools ({len(unmatched)}), needs manual review:")
        for name in unmatched:
            print(f"  {name}")


if __name__ == "__main__":
    main()
