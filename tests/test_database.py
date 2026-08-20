import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bracketballer_data.database import connection_dsn, load_env_file


class DatabaseConfigurationTests(unittest.TestCase):
    def test_database_url_takes_precedence(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://example"}, clear=True):
            self.assertEqual(connection_dsn(), "postgresql://example")

    def test_env_file_does_not_override_exported_values(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("PSQL_USER=file-user\nDEV_DB=file-db\n")
            with patch.dict(os.environ, {"PSQL_USER": "exported-user"}, clear=True):
                load_env_file(env_file)
                self.assertEqual(os.environ["PSQL_USER"], "exported-user")
                self.assertEqual(os.environ["DEV_DB"], "file-db")


if __name__ == "__main__":
    unittest.main()
