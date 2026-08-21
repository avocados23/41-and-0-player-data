"""Restore a verified development snapshot into a fresh PostgreSQL database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bracketballer_data.development_snapshot import restore_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--target-database-url",
        required=True,
        help="URL for an empty PostgreSQL 16 database after Flyway V34",
    )
    args = parser.parse_args()
    counts = restore_snapshot(
        archive=args.archive,
        manifest_path=args.manifest,
        target_dsn=args.target_database_url,
    )
    print(json.dumps({"restored_counts": counts}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
