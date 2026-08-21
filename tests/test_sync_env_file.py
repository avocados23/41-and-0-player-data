from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.sync_env_file import sync_env_file


EXAMPLE = """DATABASE_URL=postgresql://example
PSQL_USER=postgres
PSQL_PWD=test
DEV_DB=bracketballer_dev
DO_SPACES_REGION=nyc3
DO_SPACES_BUCKET=bracketballer-development-snapshots
DO_SPACES_ACCESS_KEY_ID=
DO_SPACES_SECRET_ACCESS_KEY=
"""


class SyncEnvFileTests(unittest.TestCase):
    def test_creates_private_file_from_template_and_warns_for_blank_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            example = root / ".env.example"
            env = root / ".env"
            example.write_text(EXAMPLE, encoding="utf-8")

            changed, added, blank = sync_env_file(env, example)

            self.assertTrue(changed)
            self.assertEqual(added, [
                "DO_SPACES_REGION",
                "DO_SPACES_BUCKET",
                "DO_SPACES_ACCESS_KEY_ID",
                "DO_SPACES_SECRET_ACCESS_KEY",
            ])
            self.assertEqual(set(blank), {
                "DO_SPACES_ACCESS_KEY_ID",
                "DO_SPACES_SECRET_ACCESS_KEY",
            })
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)
            self.assertEqual(env.read_text(encoding="utf-8"), EXAMPLE)

    def test_merges_only_missing_spaces_keys_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            example = root / ".env.example"
            env = root / ".env"
            example.write_text(EXAMPLE, encoding="utf-8")
            env.write_text(
                "PSQL_USER=local\nPSQL_PWD=local-secret\nDEV_DB=local_db\n"
                "DO_SPACES_ACCESS_KEY_ID=real-access\n"
                "DO_SPACES_SECRET_ACCESS_KEY=real-secret\n",
                encoding="utf-8",
            )
            env.chmod(0o644)

            changed, added, blank = sync_env_file(env, example)
            content = env.read_text(encoding="utf-8")
            self.assertTrue(changed)
            self.assertEqual(added, ["DO_SPACES_REGION", "DO_SPACES_BUCKET"])
            self.assertEqual(blank, [])
            self.assertIn("PSQL_PWD=local-secret", content)
            self.assertIn("DO_SPACES_ACCESS_KEY_ID=real-access", content)
            self.assertNotIn("DATABASE_URL=", content)
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)

            changed, added, blank = sync_env_file(env, example)
            self.assertFalse(changed)
            self.assertEqual(added, [])
            self.assertEqual(blank, [])
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)

    def test_refuses_symlinked_environment_file(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            example = root / ".env.example"
            target = root / "target.env"
            env = root / ".env"
            example.write_text(EXAMPLE, encoding="utf-8")
            target.write_text("PSQL_USER=local\n", encoding="utf-8")
            env.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "symlinked"):
                sync_env_file(env, example)


if __name__ == "__main__":
    unittest.main()
