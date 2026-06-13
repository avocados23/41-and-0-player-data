"""Process NCAA D1 men's basketball player seasons.

Reads every player_seasons/<season>/players.csv, concatenates them, computes
per-game derived stats, and selects each athlete's best season.

Run from the project root:
    python process_players.py
"""

from pathlib import Path

import pandas as pd

SEASONS_DIR = Path("player_seasons")
OUTPUT_FILE = Path("processed_players.csv")
POSITIONS_FILE = Path("player_positions.csv")

# Minimum thresholds for a season to be included in the output.
MIN_GAMES = 10
MIN_PPG = 8.0

# Map each raw source position to the canonical PG/SG/SF/PF/C positions it
# covers. Generic labels expand to every position they plausibly include, which
# is why positions are stored as a player -> position junction (1-to-many).
POSITION_MAP = {
    "PG": ["PG"],
    "SG": ["SG"],
    "SF": ["SF"],
    "PF": ["PF"],
    "C": ["C"],
    "G": ["PG", "SG"],
    "F": ["SF", "PF"],
    "G-F": ["SG", "SF"],
    "F-C": ["PF", "C"],
}

# "ATH" and a couple of unlabeled players carry no usable source position.
# They're resolved by athleteId to real positions from role/stat profile.
ATHLETE_POSITION_OVERRIDES = {
    13595: ["PG"],             # Chaze Harris (South Alabama) - slashing lead guard
    14270: ["PG"],             # Dante Harris (Georgetown) - lead point guard
    15108: ["PG"],             # Elijah Davis (Morgan State) - pass-first PG
    1741: ["PG", "SG"],        # Ahmad Harrison (St. Francis PA) - combo guard
    9436: ["PG", "SG"],        # Damian Garcia (East Texas A&M) - combo guard
    10305: ["PG", "SG"],       # DJ Armstrong Jr. (UMBC) - combo guard
    13681: ["PG", "SG"],       # Alex Mirhosseini (Ark.-Pine Bluff) - combo guard
    27620: ["PG", "SG"],       # TyTy Washington Jr. (Kentucky) - NBA combo guard
    5825: ["SG"],              # Doyel Cockrill III (Chicago State) - volume shooter
    9808: ["SG"],              # Demitri Gardner (East Carolina) - scoring guard
    1951: ["SG", "SF"],        # Chase Dawson (Morehead State) - shooting wing
    2076: ["SG", "SF"],        # Jaden Baker (Wagner) - combo guard/wing
    12510: ["SF", "PF"],       # Dalton Gayman (North Florida) - stretch forward
    34581: ["SF", "PF"],       # Eric Jamison Jr. (Gardner-Webb) - stretch forward
    41798: ["SF", "PF"],       # Ed Polite Jr. (Radford) - versatile forward
    45949: ["SF", "PF"],       # Luke Morrison (Army) - stretch four
    10164: ["PF"],             # Demariontay Hall (Coppin State) - undersized interior
    31454: ["PF", "C"],        # Sha'markus Kennedy (McNeese) - dominant big
    57544: ["C"],              # Mamadou N'Diaye (UC Irvine) - rim-protecting center
}


def build_player_positions(players: pd.DataFrame) -> pd.DataFrame:
    """Expand each player's source position into canonical PG/SG/SF/PF/C rows.

    Returns a tidy (player_id, position) frame, one row per position a player
    holds. Per-athlete overrides take precedence over the generic mapping.
    """
    rows = []
    for athlete_id, source_position in zip(players["athleteId"], players["position"]):
        positions = ATHLETE_POSITION_OVERRIDES.get(athlete_id)
        if positions is None:
            positions = POSITION_MAP.get(source_position)
        if not positions:
            continue
        for position in positions:
            rows.append({"player_id": athlete_id, "position": position})
    return pd.DataFrame(rows, columns=["player_id", "position"])


def load_all_seasons(seasons_dir: Path) -> pd.DataFrame:
    """Read every players.csv under seasons_dir and concatenate them."""
    csv_paths = sorted(seasons_dir.glob("*/players.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"No players.csv found under {seasons_dir}/")

    frames = [pd.read_csv(path) for path in csv_paths]
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    df = load_all_seasons(SEASONS_DIR)
    total_rows = len(df)

    # Keep D1 seasons only. The source data includes non-D1 opponents (and
    # pre-D1 seasons of transitioning schools); those rows have no conference.
    df = df[df["conference"].notna()]

    # Treat missing/null counting stats as 0.
    for col in ("points", "rebounds_total", "assists"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Exclude players with 0 (or missing) games to avoid division by zero.
    df["games"] = pd.to_numeric(df["games"], errors="coerce")
    df = df[df["games"] > 0].copy()

    # Derived per-game columns.
    df["PPG"] = df["points"] / df["games"]
    df["RPG"] = df["rebounds_total"] / df["games"]
    df["APG"] = df["assists"] / df["games"]
    df["tiebreaker_score"] = df["PPG"] + df["RPG"] + df["APG"]

    # Keep only seasons that clear the minimum games and scoring thresholds.
    # The PPG floor also drops any 0.0 PPG (non-scoring) seasons.
    df = df[(df["games"] >= MIN_GAMES) & (df["PPG"] >= MIN_PPG)].copy()

    # Best season per athlete: highest PPG, then highest tiebreaker_score.
    best = (
        df.sort_values(["PPG", "tiebreaker_score"], ascending=False)
        .drop_duplicates(subset="athleteId", keep="first")
        .sort_values("athleteId")
        .reset_index(drop=True)
    )

    best.to_csv(OUTPUT_FILE, index=False)

    positions = build_player_positions(best)
    positions.to_csv(POSITIONS_FILE, index=False)

    unmapped = best.loc[~best["athleteId"].isin(positions["player_id"]), "name"]

    print(f"Total player seasons processed (games > 0): {len(df)}")
    print(f"Total unique players in output:            {len(best)}")
    print(f"(Rows read across all seasons:             {total_rows})")
    print(f"Player-position rows written:              {len(positions)}")
    print(f"Players with no mapped position:           {len(unmapped)}")
    print(f"Output written to: {OUTPUT_FILE}, {POSITIONS_FILE}")


if __name__ == "__main__":
    main()
