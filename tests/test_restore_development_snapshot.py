from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import restore_development_snapshot as restore_script


class RestoreDevelopmentSnapshotCommandTests(unittest.TestCase):
    def test_default_command_discovers_snapshot_and_uses_env_database(self):
        manifest = {"release_version": "2026-08-20.1"}
        output = io.StringIO()
        with patch.object(restore_script, "load_env_file") as load_env, patch.object(
            restore_script, "connection_dsn", return_value="postgresql://env-target"
        ) as get_dsn, patch.object(
            restore_script,
            "download_latest_snapshot",
            return_value=(
                Path("/tmp/snapshot.dump"),
                Path("/tmp/snapshot.dump.sha256"),
                Path("/tmp/snapshot.dump.json"),
                manifest,
                "development-snapshots/v34/release/snapshot.dump.json",
            ),
        ) as download, patch.object(
            restore_script, "restore_snapshot", return_value={"players": 3}
        ) as restore, patch.object(
            sys, "argv", ["restore_development_snapshot.py"]
        ), patch("sys.stdout", output):
            restore_script.main()

        load_env.assert_called_once_with()
        get_dsn.assert_called_once_with()
        download.assert_called_once()
        restore.assert_called_once_with(
            archive=Path("/tmp/snapshot.dump"),
            manifest_path=Path("/tmp/snapshot.dump.json"),
            target_dsn="postgresql://env-target",
        )
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "manifest_key": "development-snapshots/v34/release/snapshot.dump.json",
                "release_version": "2026-08-20.1",
                "restored_counts": {"players": 3},
            },
        )


if __name__ == "__main__":
    unittest.main()
