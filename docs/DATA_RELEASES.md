# Production Data Release Runbook

Large sports data is versioned and audited independently from Flyway. Every
release records its pipeline commit, immutable version, source URI/checksum,
season/model range, staged and published row counts, validations, status, and
timestamps in `data_import_runs`.

`sql/bootstrap/load_core_data.sql` is local bootstrap only. Its
`TRUNCATE ... CASCADE` makes it permanently forbidden against staging or
production.

## Core schools, players, and positions

Store the three source CSVs under an immutable object-storage version and
record their object checksums. First run the publisher without `--apply`:

```bash
export DATABASE_URL=<staging-ingestion-url>
export PIPELINE_COMMIT=<full-git-commit>

python -m scripts.publish.publish_core_dataset \
  --schools data/processed/core/schools.csv \
  --players data/processed/core/processed_players.csv \
  --positions data/processed/core/player_positions.csv \
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

python -m scripts.ingest.ingest_cbbd_shots_bulk \
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
python -m scripts.compute.compute_shooting_ability_profiles \
  --first 2020 --last 2026 --version shooting-v2

python -m scripts.compute.compute_contextual_shooting_signals \
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
  -f ../fastify/database/operations/database_manifest.sql > manifest.txt
```

Compare manifests, API responses, query latency, active model, and season
aggregates. To roll back normal bad data, republish the prior immutable artifact
as a new audited release. Do not restore the whole database unless data is
catastrophically corrupted or lost.

Exceptional corrections require a reviewed Git-tracked idempotent script,
dry-run output, an exact expected row count, one transaction, staging rehearsal,
a fresh backup, and an audit row. Interactive ad-hoc production SQL is
prohibited.

## AP Top 25 + Virginia Tech rosters and defensive characteristics

Ensure the Fastify environment has the required migrations applied and keep the
CBBD SDK pinned to this repository's requirements. The ranked-roster publisher
is audited and dry-run by default:

```bash
python -m scripts.ingest.ingest_ranked_rosters \
  --season 2026 \
  --release-version ranked-rosters-2026-07-26.1

python -m scripts.ingest.ingest_ranked_rosters \
  --season 2026 \
  --release-version ranked-rosters-2026-07-26.1 \
  --apply
```

The job builds the permanent union of all AP ranks 1–25 returned for the
season plus Virginia Tech (CBBD team 340), fetches complete rosters, retains
each selected athlete's CBBD history back to 2005, and backfills every
finalized eligible-team game from season start. It fails before publication
for missing/undersized rosters, absent eligible-team lineup results,
non-five-player units, unresolved roster athletes, or unreconciled
seconds/points. Torvik matching is written to `player_seasons`; unmatched
records remain explicit and do not receive fabricated priors.

During an active season, schedule this publisher daily with a unique immutable
release version (for example, a UTC run timestamp). This is deliberately more
frequent than the required weekly AP/roster refresh and ensures newly ranked
teams are backfilled on the next run. Complete seasons need only be rerun for a
source correction.

Compute the initial model in shadow mode without activating it:

```bash
python -m scripts.compute.compute_defensive_characteristics \
  --first 2024 --last 2026 \
  --model-version defense-v1-shadow \
  --release-version defense-v1-shadow-2026-07-26.1 \
  --apply
```

The shadow version includes provisional `LIKELY_DROP_ANCHOR` scores marked
`SCHEME_LABEL_NOT_VALIDATED`. Manually review clear drop, switch, and zone
examples and calculate precision on the reviewed audit set. Activation is
blocked unless the reported precision is at least 0.80:

```bash
python -m scripts.compute.compute_defensive_characteristics \
  --first 2024 --last 2026 \
  --model-version defense-v1-shadow \
  --release-version defense-v1-activation-2026-07-27.1 \
  --scheme-validation-precision 0.84 \
  --activate --apply
```

If the audit misses the threshold, publish a new model version with
`--disable-scheme-label --activate`; that exposes the measurable traits and
`DROP_COMPATIBLE_BIG` without claiming inferred drop coverage. Active model
versions are immutable.
