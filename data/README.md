# Local pipeline data

This directory contains local, ignored pipeline inputs, caches, exports, and
review reports. It is intentionally not committed because the artifacts are
large and may contain database-derived data.

```text
data/raw/player_seasons/       CBBD player-season downloads
data/processed/core/           schools, processed players, and positions
data/cache/torvik/              rate-limited Torvik source cache
data/exports/shots/             compressed shot-event exports
data/reports/torvik/            matching and validation reports
```

The scripts create missing directories automatically. Keep production dataset
publication inputs immutable and validate them before using `--apply`.
