# Production Data Release Runbook

Large sports data is versioned and audited independently from Flyway. Every
release records its pipeline commit, immutable version, source URI/checksum,
season/model range, staged and published row counts, validations, status, and
timestamps in `data_import_runs`.

`load_data.sql` is local bootstrap only. Its `TRUNCATE ... CASCADE` makes it
permanently forbidden against staging or production.

## Core schools, players, and positions

Store the three source CSVs under an immutable object-storage version and
record their object checksums. First run the publisher without `--apply`:

```bash
export DATABASE_URL=<staging-ingestion-url>
export PIPELINE_COMMIT=<full-git-commit>

python operations/publish_core_dataset.py \
  --schools schools.csv \
  --players processed_players.csv \
  --positions player_positions.csv \
  --release-version core-2026-07-23.1 \
  --first-season 2005 \
  --last-season 2026
```

Review duplicate, foreign-key, enum, required-value, season, and 50–150% row
count bounds. Re-run with `--apply` only after review. Publication atomically
upserts source columns, refreshes position mappings for included players, and
marks missing schools/players inactive. It never deletes referenced players.

Rehearse at full volume in staging. Production requires a recent recoverable
backup, the exact same inputs/commit, and manual approval.

## CBBD shot events

```bash
export DATABASE_URL=<staging-ingestion-url>
export CBBD_API_KEY=<secret>
export PIPELINE_COMMIT=<full-git-commit>

python ingest_cbbd_shots_bulk.py \
  --first 2020 \
  --last 2026 \
  --release-version cbbd-shots-2026-07-23.1 \
  --refresh
```

Each season gets a separate audit row. The job stages all dates, creates a
deterministic checksum, verifies IDs/season/player references and row-count
bounds, then replaces that season and finishes the audit row in one publish
transaction. A fetch, validation, or publication failure leaves the prior
season visible and records a failed run.

## Shooting model

Use a new immutable model version; never overwrite an activated version.

```bash
python compute_shooting_ability_profiles.py \
  --first 2020 --last 2026 --version shooting-v2

python compute_contextual_shooting_signals.py \
  --first 2020 --last 2026 --version shooting-v2
```

The first command stores an inactive candidate and opens its audit record. The
second generates game/contextual profiles, requires exactly four zones and one
contextual profile per ability profile, activates the version, deactivates the
old version, and marks the audit published in the same transaction. Failure
cannot expose a partial candidate.

## Validation and rollback

Capture source and target manifests with:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f operations/database_manifest.sql > manifest.txt
```

Compare manifests, API responses, query latency, active model, and season
aggregates. To roll back normal bad data, republish the prior immutable artifact
as a new audited release. Do not restore the whole database unless data is
catastrophically corrupted or lost.

Exceptional corrections require a reviewed Git-tracked idempotent script,
dry-run output, an exact expected row count, one transaction, staging rehearsal,
a fresh backup, and an audit row. Interactive ad-hoc production SQL is
prohibited.
