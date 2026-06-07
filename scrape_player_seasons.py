
import csv
import os

import cbbd
from cbbd.rest import ApiException

# Defining the host is optional and defaults to https://api.collegebasketballdata.com
# See configuration.py for a list of all supported configuration parameters.
# Configure Bearer authorization: apiKey. Read the token from the environment so it
# isn't committed to source control: export CBBD_API_KEY="<your token>"
access_token = os.environ.get("CBBD_API_KEY")
if not access_token:
    raise SystemExit(
        "Missing CBBD_API_KEY environment variable. "
        'Set it before running, e.g. export CBBD_API_KEY="<your token>"'
    )
configuration = cbbd.Configuration(
    access_token = access_token
)

OUTPUT_ROOT = "player_seasons"
# 2005 (the 2004-05 season) is the first season with substantial coverage; earlier
# seasons return only a handful of players. 2026 is the latest (2025-26).
FIRST_SEASON = 2005
LAST_SEASON = 2026


def season_folder(season):
    """Folder name for a season, e.g. 2026 -> '2025-26'."""
    return f"{season - 1}-{str(season)[2:]}"


def flatten(record):
    """Flatten a PlayerSeasonStats dict, expanding nested dicts to 'parent_sub' keys."""
    flat = {}
    for key, value in record.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}_{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat


def write_season_csv(season, rows):
    """Write flattened player rows to player_seasons/<folder>/players.csv."""
    folder = os.path.join(OUTPUT_ROOT, season_folder(season))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "players.csv")

    # Collect columns preserving first-seen order across all rows (the API omits
    # null fields, so different rows can have different keys).
    columns = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(rows)
    return path


# Enter a context with an instance of the API client
with cbbd.ApiClient(configuration) as api_client:
    api_instance = cbbd.StatsApi(api_client)

    for season in range(LAST_SEASON, FIRST_SEASON - 1, -1):
        label = season_folder(season)
        try:
            api_response = api_instance.get_player_season_stats(season=season)
        except ApiException as e:
            print(f"{label}: error calling get_player_season_stats: {e}")
            continue

        if not api_response:
            print(f"{label}: no players returned, skipping")
            continue

        rows = [flatten(player.to_dict()) for player in api_response]
        write_season_csv(season, rows)
        print(f"{label}: wrote {len(rows)} players")
