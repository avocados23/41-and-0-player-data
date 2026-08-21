from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from bracketballer_data import development_snapshot as snapshot


class DevelopmentSnapshotTests(unittest.TestCase):
    def test_allowlist_excludes_application_tables(self):
        self.assertNotIn("users", snapshot.SNAPSHOT_TABLES)
        self.assertNotIn("games", snapshot.SNAPSHOT_TABLES)
        self.assertNotIn("lineup_comments", snapshot.SNAPSHOT_TABLES)
        self.assertTrue(set(snapshot.SENSITIVE_TABLES).isdisjoint(snapshot.SNAPSHOT_TABLES))

    def test_release_version_rejects_path_and_shell_characters(self):
        self.assertEqual(snapshot.validate_release_version("2026-08-20.1"), "2026-08-20.1")
        for invalid in ("../snapshot", "snapshot/$HOME", "", "x" * 129):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    snapshot.validate_release_version(invalid)

    def test_archive_table_parser_returns_only_table_data_entries(self):
        toc = """;
3655; 0 26439 TABLE DATA public players postgres
3656; 0 26440 TABLE public users postgres
3657; 0 0 SEQUENCE SET public players_id_seq postgres
"""
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "snapshot.dump"
            archive.write_bytes(b"archive")
            completed = type("Completed", (), {"stdout": toc})()
            with patch.object(snapshot.subprocess, "run", return_value=completed):
                self.assertEqual(snapshot.archive_table_data_names(archive), {"players"})

    def test_archive_allowlist_rejects_sensitive_table(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "snapshot.dump"
            archive.write_bytes(b"archive")
            with patch.object(
                snapshot,
                "archive_table_data_names",
                return_value={"players", "users"},
            ):
                with self.assertRaisesRegex(ValueError, "users"):
                    snapshot.validate_archive_allowlist(archive)

    def test_manifest_contains_checksum_size_and_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "snapshot.dump"
            archive.write_bytes(b"archive")
            with patch.object(snapshot, "validate_archive_allowlist", return_value=set()):
                manifest = snapshot.build_manifest(
                    archive=archive,
                    metadata={"server_version": "16.14", "table_counts": {"players": 1}},
                    release_version="2026-08-20.1",
                    created_at="2026-08-20T22:00:00Z",
                    object_prefix="development-snapshots/v34/20260820T220000Z/2026-08-20.1",
                    pipeline_commit="a" * 40,
                )
            self.assertEqual(manifest["archive"]["bytes"], 7)
            self.assertEqual(manifest["archive"]["sha256"], snapshot.sha256_file(archive))
            self.assertEqual(manifest["archive"]["table_allowlist"], list(snapshot.SNAPSHOT_TABLES))
            self.assertEqual(manifest["objects"]["archive"].split("/")[-1], "snapshot.dump")

    def test_validate_manifest_archive_detects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "snapshot.dump"
            archive.write_bytes(b"archive")
            manifest = {
                "format_version": snapshot.SNAPSHOT_FORMAT_VERSION,
                "archive": {
                    "filename": archive.name,
                    "bytes": archive.stat().st_size,
                    "sha256": "0" * 64,
                    "table_allowlist": list(snapshot.SNAPSHOT_TABLES),
                },
            }
            with self.assertRaisesRegex(ValueError, "checksum"):
                snapshot.validate_manifest_archive(manifest, archive)

    def test_upload_publishes_archive_checksum_then_manifest(self):
        class NoSuchKey(Exception):
            pass

        class Exceptions:
            pass

        Exceptions.NoSuchKey = NoSuchKey

        class Client:
            exceptions = Exceptions

            def __init__(self):
                self.uploads = []

            def head_object(self, **kwargs):
                raise NoSuchKey()

            def upload_file(self, path, bucket, key, ExtraArgs):
                self.uploads.append((Path(path).name, bucket, key, ExtraArgs["ContentType"]))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "snapshot.dump"
            checksum = root / "snapshot.dump.sha256"
            manifest_path = root / "snapshot.dump.json"
            archive.write_bytes(b"archive")
            digest = snapshot.sha256_file(archive)
            checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "format_version": snapshot.SNAPSHOT_FORMAT_VERSION,
                        "release_version": "2026-08-20.1",
                        "archive": {
                            "filename": archive.name,
                            "bytes": archive.stat().st_size,
                            "sha256": digest,
                            "table_allowlist": list(snapshot.SNAPSHOT_TABLES),
                        },
                        "objects": {
                            "archive": "development/a.dump",
                            "checksum": "development/a.dump.sha256",
                            "manifest": "development/a.dump.json",
                        }
                    }
                ),
                encoding="utf-8",
            )
            client = Client()
            with patch.dict(
                os.environ,
                {
                    "DO_SPACES_BUCKET": "test-bucket",
                    "DO_SPACES_ACCESS_KEY_ID": "access",
                    "DO_SPACES_SECRET_ACCESS_KEY": "secret",
                },
                clear=False,
            ), patch.object(snapshot, "spaces_client", return_value=client), patch.object(
                snapshot, "validate_archive_allowlist", return_value=set()
            ):
                result = snapshot.upload_snapshot(archive, checksum, manifest_path)
            self.assertEqual(result["bucket"], "test-bucket")
            self.assertEqual([item[2] for item in client.uploads], [
                "development/a.dump",
                "development/a.dump.sha256",
                "development/a.dump.json",
            ])

    def test_upload_skips_matching_objects_and_resumes_after_partial_upload(self):
        class NoSuchKey(Exception):
            pass

        class Exceptions:
            pass

        Exceptions.NoSuchKey = NoSuchKey

        class Client:
            exceptions = Exceptions

            def __init__(self):
                self.objects = {}
                self.uploads = []
                self.fail_manifest_once = True

            def head_object(self, *, Bucket, Key):
                if Key not in self.objects:
                    raise NoSuchKey()
                return self.objects[Key]

            def upload_file(self, path, bucket, key, ExtraArgs):
                self.uploads.append(key)
                if key.endswith(".json") and self.fail_manifest_once:
                    self.fail_manifest_once = False
                    raise RuntimeError("simulated interruption")
                self.objects[key] = {
                    "Metadata": ExtraArgs["Metadata"],
                    "ContentLength": Path(path).stat().st_size,
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "snapshot.dump"
            checksum = root / "snapshot.dump.sha256"
            manifest_path = root / "snapshot.dump.json"
            archive.write_bytes(b"archive")
            digest = snapshot.sha256_file(archive)
            checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "format_version": snapshot.SNAPSHOT_FORMAT_VERSION,
                        "release_version": "2026-08-20.1",
                        "archive": {
                            "filename": archive.name,
                            "bytes": archive.stat().st_size,
                            "sha256": digest,
                            "table_allowlist": list(snapshot.SNAPSHOT_TABLES),
                        },
                        "objects": {
                            "archive": "development/a.dump",
                            "checksum": "development/a.dump.sha256",
                            "manifest": "development/a.dump.json",
                        },
                    }
                ),
                encoding="utf-8",
            )
            client = Client()
            with patch.dict(
                os.environ,
                {
                    "DO_SPACES_BUCKET": "test-bucket",
                    "DO_SPACES_ACCESS_KEY_ID": "access",
                    "DO_SPACES_SECRET_ACCESS_KEY": "secret",
                },
                clear=False,
            ), patch.object(snapshot, "spaces_client", return_value=client), patch.object(
                snapshot, "validate_archive_allowlist", return_value=set()
            ):
                with self.assertRaisesRegex(RuntimeError, "interruption"):
                    snapshot.upload_snapshot(archive, checksum, manifest_path)
                snapshot.upload_snapshot(archive, checksum, manifest_path)

            self.assertEqual(client.uploads, [
                "development/a.dump",
                "development/a.dump.sha256",
                "development/a.dump.json",
                "development/a.dump.json",
            ])

    def test_upload_rejects_existing_object_without_matching_metadata(self):
        class NoSuchKey(Exception):
            pass

        class Exceptions:
            pass

        Exceptions.NoSuchKey = NoSuchKey

        class Client:
            exceptions = Exceptions

            def head_object(self, **kwargs):
                return {"Metadata": {"snapshot-release": "different"}}

            def upload_file(self, *args, **kwargs):
                raise AssertionError("mismatched object must not be overwritten")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "snapshot.dump"
            checksum = root / "snapshot.dump.sha256"
            manifest_path = root / "snapshot.dump.json"
            archive.write_bytes(b"archive")
            digest = snapshot.sha256_file(archive)
            checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "format_version": snapshot.SNAPSHOT_FORMAT_VERSION,
                        "release_version": "2026-08-20.1",
                        "archive": {
                            "filename": archive.name,
                            "bytes": archive.stat().st_size,
                            "sha256": digest,
                            "table_allowlist": list(snapshot.SNAPSHOT_TABLES),
                        },
                        "objects": {
                            "archive": "development/a.dump",
                            "checksum": "development/a.dump.sha256",
                            "manifest": "development/a.dump.json",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "DO_SPACES_BUCKET": "test-bucket",
                    "DO_SPACES_ACCESS_KEY_ID": "access",
                    "DO_SPACES_SECRET_ACCESS_KEY": "secret",
                },
                clear=False,
            ), patch.object(snapshot, "spaces_client", return_value=Client()), patch.object(
                snapshot, "validate_archive_allowlist", return_value=set()
            ):
                with self.assertRaisesRegex(FileExistsError, "mismatched"):
                    snapshot.upload_snapshot(archive, checksum, manifest_path)

    def test_spaces_client_normalizes_bucket_endpoint(self):
        with patch.dict(
            os.environ,
            {
                "DO_SPACES_REGION": "nyc3",
                "DO_SPACES_BUCKET": "test-bucket",
                "DO_SPACES_ACCESS_KEY_ID": "access",
                "DO_SPACES_SECRET_ACCESS_KEY": "secret",
                "DO_SPACES_ENDPOINT": "https://test-bucket.nyc3.digitaloceanspaces.com",
            },
            clear=False,
        ):
            url = snapshot.spaces_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": "test-bucket", "Key": "development/a.dump"},
                ExpiresIn=60,
            )
        self.assertTrue(
            url.startswith("https://test-bucket.nyc3.digitaloceanspaces.com/development/a.dump?")
        )

    def test_download_latest_snapshot_paginates_and_skips_incomplete_release(self):
        class NoSuchKey(Exception):
            pass

        class Exceptions:
            pass

        Exceptions.NoSuchKey = NoSuchKey

        class Client:
            exceptions = Exceptions

            def __init__(self, objects):
                self.objects = objects
                self.list_calls = []
                self.downloads = []

            def list_objects_v2(self, **kwargs):
                self.list_calls.append(kwargs)
                if "ContinuationToken" not in kwargs:
                    return {
                        "Contents": [
                            {
                                "Key": "development-snapshots/v34/new/snapshot.dump.json",
                                "LastModified": datetime(2026, 8, 20, tzinfo=timezone.utc),
                            }
                        ],
                        "IsTruncated": True,
                        "NextContinuationToken": "next-page",
                    }
                return {
                    "Contents": [
                        {
                            "Key": "development-snapshots/v34/old/snapshot.dump.json",
                            "LastModified": datetime(2026, 8, 19, tzinfo=timezone.utc),
                        },
                        {"Key": "development-snapshots/v34/old/README.txt"},
                    ],
                    "IsTruncated": False,
                }

            def head_object(self, *, Bucket, Key):
                if Key not in self.objects:
                    raise NoSuchKey()
                return {"ContentLength": len(self.objects[Key])}

            def download_file(self, bucket, key, filename):
                self.downloads.append(key)
                if key not in self.objects:
                    raise NoSuchKey()
                Path(filename).write_bytes(self.objects[key])

        archive = b"verified archive"
        digest = snapshot.hashlib.sha256(archive).hexdigest()

        def manifest_for(prefix):
            return json.dumps(
                {
                    "format_version": snapshot.SNAPSHOT_FORMAT_VERSION,
                    "release_version": prefix,
                    "archive": {
                        "filename": "snapshot.dump",
                        "bytes": len(archive),
                        "sha256": digest,
                        "table_allowlist": list(snapshot.SNAPSHOT_TABLES),
                    },
                    "objects": {
                        "archive": f"development-snapshots/v34/{prefix}/snapshot.dump",
                        "checksum": f"development-snapshots/v34/{prefix}/snapshot.dump.sha256",
                        "manifest": f"development-snapshots/v34/{prefix}/snapshot.dump.json",
                    },
                }
            ).encode()

        objects = {
            "development-snapshots/v34/new/snapshot.dump.json": manifest_for("new"),
            "development-snapshots/v34/old/snapshot.dump.json": manifest_for("old"),
            "development-snapshots/v34/old/snapshot.dump": archive,
            "development-snapshots/v34/old/snapshot.dump.sha256": (
                f"{digest}  snapshot.dump\n".encode()
            ),
        }
        client = Client(objects)
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "DO_SPACES_BUCKET": "test-bucket",
                "DO_SPACES_ACCESS_KEY_ID": "access",
                "DO_SPACES_SECRET_ACCESS_KEY": "secret",
            },
            clear=False,
        ), patch.object(snapshot, "spaces_client", return_value=client), patch.object(
            snapshot, "validate_manifest_archive"
        ):
            archive_path, checksum_path, manifest_path, manifest, manifest_key = (
                snapshot.download_latest_snapshot(Path(directory))
            )

            self.assertEqual(manifest_key, "development-snapshots/v34/old/snapshot.dump.json")
            self.assertEqual(manifest["release_version"], "old")
            self.assertEqual(archive_path.read_bytes(), archive)
            self.assertEqual(checksum_path.read_text(), f"{digest}  snapshot.dump\n")
            self.assertEqual(manifest_path.read_text(), objects[manifest_key].decode())
            self.assertEqual(len(client.list_calls), 2)
            self.assertEqual(
                client.list_calls[1]["ContinuationToken"],
                "next-page",
            )
            self.assertNotIn("development-snapshots/v34/new/snapshot.dump", client.downloads)

    def test_download_latest_snapshot_rejects_manifest_key_mismatch(self):
        class NoSuchKey(Exception):
            pass

        class Exceptions:
            pass

        Exceptions.NoSuchKey = NoSuchKey

        class Client:
            exceptions = Exceptions

            def list_objects_v2(self, **kwargs):
                return {
                    "Contents": [
                        {
                            "Key": "development-snapshots/v34/release/snapshot.dump.json",
                            "LastModified": datetime(2026, 8, 20, tzinfo=timezone.utc),
                        }
                    ]
                }

            def download_file(self, bucket, key, filename):
                Path(filename).write_text(
                    json.dumps(
                        {
                            "objects": {
                                "archive": "other.dump",
                                "checksum": "other.dump.sha256",
                                "manifest": "different.json",
                            }
                        }
                    ),
                    encoding="utf-8",
                )

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "DO_SPACES_BUCKET": "test-bucket",
                "DO_SPACES_ACCESS_KEY_ID": "access",
                "DO_SPACES_SECRET_ACCESS_KEY": "secret",
            },
            clear=False,
        ), patch.object(snapshot, "spaces_client", return_value=Client()):
            with self.assertRaisesRegex(ValueError, "does not match"):
                snapshot.download_latest_snapshot(Path(directory))


if __name__ == "__main__":
    unittest.main()
