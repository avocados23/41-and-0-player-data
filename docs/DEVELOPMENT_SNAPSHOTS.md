# Development database snapshots

Development snapshots contain the player, school, defensive, shot-event, and
derived shooting data needed by the application. They intentionally contain no
users, games, queues, draft picks, comments, votes, labels, or published
lineups. Synthetic application records can be created separately for workflow
testing.

The snapshot format is PostgreSQL 16 custom-format, data-only, compressed with
Zstandard. The target schema must be created by the Fastify repository's
Flyway migrations through V34 before the data is restored.

## Spaces setup

Create a private DigitalOcean Space in `nyc3` named
`bracketballer-development-snapshots`. Keep public file listing and the CDN
disabled. Configure lifecycle expiration for the
`development-snapshots/` prefix after 90 days and incomplete multipart uploads
after one day.

Create a bucket-scoped Spaces access key with read/write/delete permission for
the publisher. Keep the key in the operator's password manager or an approved
secret store; do not commit it or place it in a shared shell history.

DigitalOcean Spaces configuration is optional for local creation and restore.
Set these values in the ignored `.env` only when publishing or sharing:

```text
DO_SPACES_REGION=nyc3
DO_SPACES_BUCKET=bracketballer-development-snapshots
DO_SPACES_ACCESS_KEY_ID=<publisher-key>
DO_SPACES_SECRET_ACCESS_KEY=<publisher-secret>
```

`./scripts/setup-local.sh` creates `.env` when absent and appends only missing
Spaces settings when it already exists. Existing database and API settings are
preserved; real Spaces credentials must be entered through an approved secret
channel. The optional `DO_SPACES_ENDPOINT` may be omitted (the region endpoint
is inferred), and a bucket hostname is normalized safely if it is supplied.

## Create and publish

Use a unique release version. Creation reads the source database in one
repeatable-read snapshot, verifies PostgreSQL 16 and Flyway V34, writes the
archive, checksum, and JSON manifest locally, and refuses to overwrite an
existing archive.

```bash
.venv/bin/python -m scripts.publish.publish_development_snapshot \
  create --release-version 2026-08-20.1

.venv/bin/python -m scripts.publish.publish_development_snapshot \
  upload \
  --archive data/exports/development/bracketballer-player-school-data-v34-2026-08-20.1.dump \
  --manifest data/exports/development/bracketballer-player-school-data-v34-2026-08-20.1.dump.json
```

The upload validates the archive, manifest, and checksum sidecar before making
any network request, then publishes the archive and checksum first and the
manifest last. Object keys are immutable and are never overwritten: an
interrupted retry skips objects with matching SHA-256/release metadata and
rejects mismatches (including legacy objects that lack the metadata). Use a new
release version when republishing an object created by an older uploader. The
manifest records the source Flyway checksums, source commit, exact row counts,
archive size, SHA-256, and object keys.

The developer restore command discovers the newest complete release directly
from Spaces. Give the developer a read-only, bucket-scoped Spaces key and add
the following settings to the developer's ignored `.env`:

```text
DO_SPACES_REGION=nyc3
DO_SPACES_BUCKET=bracketballer-development-snapshots
DO_SPACES_ACCESS_KEY_ID=<developer-read-key>
DO_SPACES_SECRET_ACCESS_KEY=<developer-read-secret>
```

The script does not require a manifest path, object key, release version, or
download URL from the developer. It lists published manifests, downloads the
newest complete snapshot, verifies it, restores it, and removes its temporary
files:

```bash
.venv/bin/python scripts/restore_development_snapshot.py
```

## Restore locally

Create a fresh PostgreSQL 16 database, apply the Fastify Flyway migrations
through V34, and set its connection string in `DATABASE_URL` (or configure the
existing `PSQL_*` settings). The command above uses that target automatically.
It refuses a nonempty or schema-mismatched target.

For an operator who already has local snapshot artifacts, the explicit form is
still available:

```bash
.venv/bin/python scripts/restore_development_snapshot.py \
  --archive snapshot.dump \
  --manifest snapshot.dump.json \
  --target-database-url '<empty-target-database-url>'
```

The restore command refuses a nonempty target, requires the target Flyway
history and checksums to match the manifest, restores in one transaction,
runs `ANALYZE`, and compares every allowlisted table count. It also verifies
that all sensitive application tables remain empty.

Docker and native PostgreSQL servers use the same archive and restore command;
only the target database URL and provisioning steps differ.

## Snapshot contents

The explicit allowlist is maintained in
`src/bracketballer_data/development_snapshot.py`. Adding a new sports-data
table requires a deliberate code and test change. A snapshot archive is kept
under ignored `data/` storage and must never be committed to Git or Git LFS.
