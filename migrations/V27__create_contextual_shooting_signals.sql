-- Contextual signals derived from the immutable shot events and shooting-v1
-- zone posteriors. Game rows make every season-level signal auditable.
CREATE TABLE player_shooting_game_profiles (
    player_id                    INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    season                       SMALLINT NOT NULL,
    model_version                TEXT NOT NULL REFERENCES shooting_model_versions (version) ON DELETE CASCADE,
    game_id                      BIGINT NOT NULL,
    game_start_date              TIMESTAMPTZ,
    opponent_id                  INTEGER,
    opponent                     TEXT,
    season_type                  TEXT,
    tournament                   TEXT,
    field_goal_attempts          INTEGER NOT NULL,
    field_goals_made             INTEGER NOT NULL,
    three_point_attempts         INTEGER NOT NULL,
    three_points_made            INTEGER NOT NULL,
    free_throw_attempts          INTEGER NOT NULL,
    free_throws_made             INTEGER NOT NULL,
    rim_attempts                 INTEGER NOT NULL,
    jumper_attempts              INTEGER NOT NULL,
    points                       INTEGER NOT NULL,
    shooting_possessions         DOUBLE PRECISION NOT NULL,
    expected_league_points       DOUBLE PRECISION NOT NULL,
    expected_player_points       DOUBLE PRECISION NOT NULL,
    execution_above_expected     DOUBLE PRECISION NOT NULL,
    late_close_fga               INTEGER NOT NULL,
    late_close_three_pa          INTEGER NOT NULL,
    late_close_fta               INTEGER NOT NULL,
    late_close_points            INTEGER NOT NULL,
    late_close_expected_points   DOUBLE PRECISION NOT NULL,
    assisted_perimeter_makes     INTEGER NOT NULL,
    perimeter_makes              INTEGER NOT NULL,
    computed_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, season, model_version, game_id),
    CONSTRAINT player_shooting_game_counts_chk CHECK (
        field_goal_attempts >= 0 AND field_goals_made BETWEEN 0 AND field_goal_attempts
        AND three_point_attempts >= 0 AND three_points_made BETWEEN 0 AND three_point_attempts
        AND free_throw_attempts >= 0 AND free_throws_made BETWEEN 0 AND free_throw_attempts
        AND late_close_fga >= 0 AND late_close_three_pa >= 0 AND late_close_fta >= 0
    )
);

CREATE INDEX player_shooting_game_context_idx
    ON player_shooting_game_profiles (model_version, season, player_id);
CREATE INDEX player_shooting_game_opponent_idx
    ON player_shooting_game_profiles (model_version, season, opponent_id);

CREATE TABLE player_contextual_shooting_profiles (
    player_id                         INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    season                            SMALLINT NOT NULL,
    model_version                     TEXT NOT NULL REFERENCES shooting_model_versions (version) ON DELETE CASCADE,

    clutch_games                      INTEGER NOT NULL,
    clutch_fga                        INTEGER NOT NULL,
    clutch_three_pa                   INTEGER NOT NULL,
    clutch_fta                        INTEGER NOT NULL,
    clutch_points                     INTEGER NOT NULL,
    clutch_efg_pct                    DOUBLE PRECISION,
    clutch_true_shooting_pct          DOUBLE PRECISION,
    clutch_points_above_expected      DOUBLE PRECISION,
    clutch_score                      DOUBLE PRECISION,
    clutch_confidence                 DOUBLE PRECISION NOT NULL,
    clutch_delta_p10                  DOUBLE PRECISION,
    clutch_delta_p90                  DOUBLE PRECISION,

    median_game_execution             DOUBLE PRECISION NOT NULL,
    execution_mad                     DOUBLE PRECISION NOT NULL,
    shooting_floor                    DOUBLE PRECISION NOT NULL,
    shooting_ceiling                  DOUBLE PRECISION NOT NULL,
    above_expectation_game_rate       DOUBLE PRECISION NOT NULL,
    consistency_score                 DOUBLE PRECISION NOT NULL,
    volatility_score                  DOUBLE PRECISION NOT NULL,

    selection_value_per_100_fga       DOUBLE PRECISION NOT NULL,
    selection_score                   DOUBLE PRECISION NOT NULL,
    rim_pressure_per40                DOUBLE PRECISION NOT NULL,
    rim_pressure_score                DOUBLE PRECISION NOT NULL,
    assisted_perimeter_make_rate      DOUBLE PRECISION,
    scalability_score                 DOUBLE PRECISION NOT NULL,

    postseason_possessions            DOUBLE PRECISION NOT NULL,
    postseason_points_above_expected  DOUBLE PRECISION,
    postseason_score                  DOUBLE PRECISION,
    postseason_confidence             DOUBLE PRECISION NOT NULL,

    strong_opponent_possessions       DOUBLE PRECISION NOT NULL,
    matchup_points_above_expected     DOUBLE PRECISION,
    matchup_resistance_score          DOUBLE PRECISION,
    matchup_confidence                DOUBLE PRECISION NOT NULL,

    role_labels                       JSONB NOT NULL DEFAULT '[]'::jsonb,
    computed_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, season, model_version),
    CONSTRAINT player_contextual_shooting_rates_chk CHECK (
        (clutch_efg_pct IS NULL OR clutch_efg_pct >= 0)
        AND (clutch_true_shooting_pct IS NULL OR clutch_true_shooting_pct >= 0)
        AND above_expectation_game_rate BETWEEN 0 AND 1
        AND (assisted_perimeter_make_rate IS NULL OR assisted_perimeter_make_rate BETWEEN 0 AND 1)
    ),
    CONSTRAINT player_contextual_shooting_scores_chk CHECK (
        (clutch_score IS NULL OR clutch_score BETWEEN 0 AND 100)
        AND clutch_confidence BETWEEN 0 AND 100
        AND consistency_score BETWEEN 0 AND 100
        AND volatility_score BETWEEN 0 AND 100
        AND selection_score BETWEEN 0 AND 100
        AND rim_pressure_score BETWEEN 0 AND 100
        AND scalability_score BETWEEN 0 AND 100
        AND (postseason_score IS NULL OR postseason_score BETWEEN 0 AND 100)
        AND postseason_confidence BETWEEN 0 AND 100
        AND (matchup_resistance_score IS NULL OR matchup_resistance_score BETWEEN 0 AND 100)
        AND matchup_confidence BETWEEN 0 AND 100
    )
);

CREATE INDEX player_contextual_shooting_labels_idx
    ON player_contextual_shooting_profiles USING GIN (role_labels);
CREATE INDEX player_contextual_shooting_clutch_idx
    ON player_contextual_shooting_profiles (model_version, season, clutch_score DESC);
