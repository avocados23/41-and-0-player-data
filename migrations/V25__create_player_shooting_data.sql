-- Raw CBBD shooting plays plus a derived, application-facing shooter signal.
-- player_shot_events preserves the original CBBD response in raw_payload while
-- promoting the fields used for shot charts and signal computation.
CREATE TABLE player_shot_events (
    source_play_id          BIGINT PRIMARY KEY,
    source_id               TEXT NOT NULL,
    player_id               INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    season                  SMALLINT NOT NULL,

    game_id                 BIGINT NOT NULL,
    game_source_id          TEXT,
    game_start_date         TIMESTAMPTZ,
    season_type             TEXT,
    play_type               TEXT,
    team_id                 INTEGER,
    team                    TEXT,
    opponent_id             INTEGER,
    opponent                TEXT,
    period                  SMALLINT,
    clock                   TEXT,
    seconds_remaining       SMALLINT,
    play_text               TEXT,

    made                    BOOLEAN,
    shot_range              TEXT,
    assisted                BOOLEAN,
    assisted_by_player_id   INTEGER,
    assisted_by_name        TEXT,
    location_x              DOUBLE PRECISION,
    location_y              DOUBLE PRECISION,

    raw_payload             JSONB NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT player_shot_events_season_chk CHECK (season BETWEEN 1900 AND 2100)
);

CREATE INDEX player_shot_events_player_season_idx
    ON player_shot_events (player_id, season);
CREATE INDEX player_shot_events_game_id_idx
    ON player_shot_events (game_id);
CREATE INDEX player_shot_events_season_range_idx
    ON player_shot_events (season, shot_range);

-- A row records the outcome of the latest full player-season fetch. This lets
-- the ingestion job resume without treating a legitimate empty response as a
-- player that still needs to be fetched.
CREATE TABLE player_shooting_ingestion_status (
    player_id       INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    season          SMALLINT NOT NULL,
    status          TEXT NOT NULL,
    event_count     INTEGER NOT NULL DEFAULT 0,
    attempt_count   INTEGER NOT NULL DEFAULT 1,
    error_message   TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, season),
    CONSTRAINT player_shooting_ingestion_status_value_chk
        CHECK (status IN ('success', 'no_data', 'failed')),
    CONSTRAINT player_shooting_ingestion_event_count_chk CHECK (event_count >= 0)
);

CREATE INDEX player_shooting_ingestion_status_status_idx
    ON player_shooting_ingestion_status (season, status);

-- Detailed features stay separate from players so the scoring model can evolve
-- without widening the application's core player record for every new metric.
CREATE TABLE player_shooting_profiles (
    player_id                 INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    season                    SMALLINT NOT NULL,
    shooting_events           INTEGER NOT NULL,
    field_goal_attempts       INTEGER NOT NULL,
    free_throw_attempts       INTEGER NOT NULL,
    three_point_attempts      INTEGER NOT NULL,
    three_point_made          INTEGER NOT NULL,
    raw_three_point_pct       DOUBLE PRECISION,
    adjusted_three_point_pct  DOUBLE PRECISION,
    three_point_attempts_pg   DOUBLE PRECISION NOT NULL,
    three_point_attempt_share DOUBLE PRECISION NOT NULL,
    assisted_three_rate       DOUBLE PRECISION,
    coordinate_coverage       DOUBLE PRECISION,
    shooter_score             SMALLINT NOT NULL,
    is_shooter                BOOLEAN NOT NULL,
    computed_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, season),
    CONSTRAINT player_shooting_profiles_score_chk
        CHECK (shooter_score BETWEEN 0 AND 100),
    CONSTRAINT player_shooting_profiles_counts_chk
        CHECK (
            shooting_events >= 0 AND field_goal_attempts >= 0
            AND free_throw_attempts >= 0 AND three_point_attempts >= 0
            AND three_point_made >= 0
        )
);

CREATE INDEX player_shooting_profiles_season_score_idx
    ON player_shooting_profiles (season, shooter_score DESC);
CREATE INDEX player_shooting_profiles_shooter_idx
    ON player_shooting_profiles (is_shooter, shooter_score DESC)
    WHERE is_shooter;

ALTER TABLE players
    ADD COLUMN shooter_score SMALLINT,
    ADD COLUMN is_shooter BOOLEAN,
    ADD CONSTRAINT players_shooter_score_chk
        CHECK (shooter_score BETWEEN 0 AND 100);

CREATE INDEX players_is_shooter_idx
    ON players (is_shooter, shooter_score DESC)
    WHERE is_shooter;
