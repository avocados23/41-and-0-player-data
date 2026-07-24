-- Audit every large sports-data or model publication independently from
-- Flyway schema history. Jobs create a running row before staging data and
-- finish it only after validation and the publish transaction succeed.
CREATE TABLE data_import_runs (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset               TEXT NOT NULL,
    import_version        TEXT NOT NULL,
    pipeline_commit       TEXT NOT NULL,
    source_uri            TEXT NOT NULL,
    source_sha256         TEXT,
    first_season          SMALLINT,
    last_season           SMALLINT,
    model_version         TEXT,
    status                TEXT NOT NULL DEFAULT 'running',
    staged_row_counts     JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_row_counts  JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_results    JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    validated_at          TIMESTAMPTZ,
    published_at          TIMESTAMPTZ,
    finished_at           TIMESTAMPTZ,
    error_message         TEXT,
    CONSTRAINT data_import_runs_status_chk CHECK (
        status IN ('running', 'validated', 'published', 'failed')
    ),
    CONSTRAINT data_import_runs_sha256_chk CHECK (
        source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT data_import_runs_commit_chk CHECK (
        pipeline_commit ~ '^[0-9a-f]{7,64}$'
    ),
    CONSTRAINT data_import_runs_seasons_chk CHECK (
        (first_season IS NULL AND last_season IS NULL)
        OR (
            first_season BETWEEN 1900 AND 2100
            AND last_season BETWEEN first_season AND 2100
        )
    ),
    CONSTRAINT data_import_runs_lifecycle_chk CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status = 'validated' AND validated_at IS NOT NULL AND finished_at IS NULL)
        OR (
            status = 'published'
            AND source_sha256 IS NOT NULL
            AND validated_at IS NOT NULL
            AND published_at IS NOT NULL
            AND finished_at IS NOT NULL
        )
        OR (status = 'failed' AND finished_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX data_import_runs_release_idx
    ON data_import_runs (dataset, import_version);
CREATE INDEX data_import_runs_status_started_idx
    ON data_import_runs (status, started_at DESC);
CREATE INDEX data_import_runs_model_version_idx
    ON data_import_runs (model_version)
    WHERE model_version IS NOT NULL;

-- Source refreshes retire records instead of deleting rows that may already be
-- referenced by games, analytics, or community content.
ALTER TABLE schools
    ADD COLUMN source_active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN source_updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE players
    ADD COLUMN source_active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN source_updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE player_defensive_stats
    ADD COLUMN source_active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN source_updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX schools_source_active_idx ON schools (source_active);
CREATE INDEX players_source_active_season_idx ON players (source_active, season);
CREATE INDEX player_defensive_stats_source_active_season_idx
    ON player_defensive_stats (source_active, season);
