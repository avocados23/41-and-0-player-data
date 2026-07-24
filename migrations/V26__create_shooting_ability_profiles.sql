-- Versioned, application-facing shooting ability model. The original
-- player_shooting_profiles table remains intact as the legacy "shooter"
-- classifier; these tables hold the richer model used to combine lineups.
CREATE TABLE shooting_model_versions (
    version         TEXT PRIMARY KEY,
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    configuration  JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at    TIMESTAMPTZ
);

CREATE UNIQUE INDEX shooting_model_versions_one_active_idx
    ON shooting_model_versions (is_active)
    WHERE is_active;

CREATE TABLE player_shooting_ability_profiles (
    player_id                                  INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    season                                     SMALLINT NOT NULL,
    model_version                              TEXT NOT NULL REFERENCES shooting_model_versions (version) ON DELETE CASCADE,
    games                                      INTEGER NOT NULL,
    minutes                                    INTEGER NOT NULL,
    tracked_events                             INTEGER NOT NULL,
    field_goal_attempts                        INTEGER NOT NULL,
    free_throw_attempts                        INTEGER NOT NULL,
    field_goal_attempts_per40                  DOUBLE PRECISION NOT NULL,
    event_coverage                             DOUBLE PRECISION NOT NULL,
    expected_points_per_100_fga                DOUBLE PRECISION NOT NULL,
    expected_points_per_100_shooting_possessions DOUBLE PRECISION NOT NULL,
    efficiency_score                           DOUBLE PRECISION NOT NULL,
    shot_making_above_average                  DOUBLE PRECISION NOT NULL,
    shot_making_score                          DOUBLE PRECISION NOT NULL,
    spacing_score                              DOUBLE PRECISION NOT NULL,
    versatility_score                          DOUBLE PRECISION NOT NULL,
    self_creation_score                        DOUBLE PRECISION NOT NULL,
    free_throw_score                           DOUBLE PRECISION NOT NULL,
    confidence_score                           DOUBLE PRECISION NOT NULL,
    shooting_ability_score                     DOUBLE PRECISION NOT NULL,
    ability_p10                                DOUBLE PRECISION NOT NULL,
    ability_p50                                DOUBLE PRECISION NOT NULL,
    ability_p90                                DOUBLE PRECISION NOT NULL,
    expected_points_p10                        DOUBLE PRECISION NOT NULL,
    expected_points_p50                        DOUBLE PRECISION NOT NULL,
    expected_points_p90                        DOUBLE PRECISION NOT NULL,
    computed_at                                TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, season, model_version),
    CONSTRAINT player_shooting_ability_counts_chk CHECK (
        games >= 0 AND minutes > 0 AND tracked_events > 0
        AND field_goal_attempts >= 0 AND free_throw_attempts >= 0
    ),
    CONSTRAINT player_shooting_ability_coverage_chk CHECK (event_coverage BETWEEN 0 AND 1),
    CONSTRAINT player_shooting_ability_scores_chk CHECK (
        efficiency_score BETWEEN 0 AND 100
        AND shot_making_score BETWEEN 0 AND 100
        AND spacing_score BETWEEN 0 AND 100
        AND versatility_score BETWEEN 0 AND 100
        AND self_creation_score BETWEEN 0 AND 100
        AND free_throw_score BETWEEN 0 AND 100
        AND confidence_score BETWEEN 0 AND 100
        AND shooting_ability_score BETWEEN 0 AND 100
        AND ability_p10 BETWEEN 0 AND 100
        AND ability_p50 BETWEEN 0 AND 100
        AND ability_p90 BETWEEN 0 AND 100
    )
);

CREATE INDEX player_shooting_ability_active_lookup_idx
    ON player_shooting_ability_profiles (model_version, player_id);
CREATE INDEX player_shooting_ability_season_score_idx
    ON player_shooting_ability_profiles (model_version, season, shooting_ability_score DESC);

CREATE TABLE player_shooting_zone_profiles (
    player_id            INTEGER NOT NULL,
    season               SMALLINT NOT NULL,
    model_version        TEXT NOT NULL,
    zone                 TEXT NOT NULL,
    attempts             INTEGER NOT NULL,
    makes                INTEGER NOT NULL,
    attempts_per40       DOUBLE PRECISION NOT NULL,
    attempt_share        DOUBLE PRECISION NOT NULL,
    league_average       DOUBLE PRECISION NOT NULL,
    prior_alpha          DOUBLE PRECISION NOT NULL,
    prior_beta           DOUBLE PRECISION NOT NULL,
    posterior_alpha      DOUBLE PRECISION NOT NULL,
    posterior_beta       DOUBLE PRECISION NOT NULL,
    adjusted_accuracy    DOUBLE PRECISION NOT NULL,
    threat_probability   DOUBLE PRECISION NOT NULL,
    threat_score         DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (player_id, season, model_version, zone),
    FOREIGN KEY (player_id, season, model_version)
        REFERENCES player_shooting_ability_profiles (player_id, season, model_version)
        ON DELETE CASCADE,
    CONSTRAINT player_shooting_zone_value_chk
        CHECK (zone IN ('rim', 'jumper', 'three_pointer', 'free_throw')),
    CONSTRAINT player_shooting_zone_counts_chk
        CHECK (attempts >= 0 AND makes >= 0 AND makes <= attempts),
    CONSTRAINT player_shooting_zone_rates_chk CHECK (
        attempt_share BETWEEN 0 AND 1
        AND league_average BETWEEN 0 AND 1
        AND adjusted_accuracy BETWEEN 0 AND 1
        AND threat_probability BETWEEN 0 AND 1
        AND threat_score BETWEEN 0 AND 1
    )
);

CREATE INDEX player_shooting_zone_model_lookup_idx
    ON player_shooting_zone_profiles (model_version, player_id, zone);
