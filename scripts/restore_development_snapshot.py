"""Download and restore the latest verified development snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from bracketballer_data.database import connection_dsn, load_env_file
from bracketballer_data.development_snapshot import download_latest_snapshot, restore_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        help="use a local archive instead of downloading the latest Spaces snapshot",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="use a local manifest instead of downloading the latest Spaces snapshot",
    )
    parser.add_argument(
        "--target-database-url",
        help="override DATABASE_URL for an empty PostgreSQL 16 database after Flyway V34",
    )
    args = parser.parse_args()
    if (args.archive is None) != (args.manifest is None):
        parser.error("--archive and --manifest must be supplied together")

    load_env_file()
    target_dsn = args.target_database_url or connection_dsn()
    if args.archive is not None and args.manifest is not None:
        counts = restore_snapshot(
            archive=args.archive,
            manifest_path=args.manifest,
            target_dsn=target_dsn,
        )
        print(json.dumps({"restored_counts": counts}, indent=2, sort_keys=True))
        return

    with TemporaryDirectory(prefix="bracketballer-development-snapshot-") as directory:
        archive, _, manifest_path, manifest, manifest_key = download_latest_snapshot(
            Path(directory)
        )
        counts = restore_snapshot(
            archive=archive,
            manifest_path=manifest_path,
            target_dsn=target_dsn,
        )
    print(
        json.dumps(
            {
                "manifest_key": manifest_key,
                "release_version": manifest.get("release_version"),
                "restored_counts": counts,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
