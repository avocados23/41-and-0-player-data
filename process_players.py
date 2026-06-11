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

    # Best season per athlete: highest PPG, then highest tiebreaker_score.
    best = (
        df.sort_values(["PPG", "tiebreaker_score"], ascending=False)
        .drop_duplicates(subset="athleteId", keep="first")
        .sort_values("athleteId")
        .reset_index(drop=True)
    )

    best.to_csv(OUTPUT_FILE, index=False)

    print(f"Total player seasons processed (games > 0): {len(df)}")
    print(f"Total unique players in output:            {len(best)}")
    print(f"(Rows read across all seasons:             {total_rows})")
    print(f"Output written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
