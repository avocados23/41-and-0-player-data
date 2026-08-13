-- AP Top 25 + Virginia Tech roster and defensive-characteristic foundation.
-- The existing players row remains backward compatible as the application's
-- best-season projection while player_seasons becomes the season/team truth.

ALTER TABLE players
    ADD COLUMN source_id TEXT;

ALTER TABLE players
    ALTER COLUMN school_id DROP NOT NULL,
    ALTER COLUMN conference DROP NOT NULL,
    ALTER COLUMN season DROP NOT NULL,
    ALTER COLUMN games DROP NOT NULL,
    ALTER COLUMN starts DROP NOT NULL,
    ALTER COLUMN minutes DROP NOT NULL,
    ALTER COLUMN points DROP NOT NULL,
    ALTER COLUMN turnovers DROP NOT NULL,
    ALTER COLUMN fouls DROP NOT NULL,
    ALTER COLUMN assists DROP NOT NULL,
    ALTER COLUMN steals DROP NOT NULL,
    ALTER COLUMN blocks DROP NOT NULL,
    ALTER COLUMN field_goals_attempted DROP NOT NULL,
    ALTER COLUMN field_goals_made DROP NOT NULL,
    ALTER COLUMN two_point_field_goals_attempted DROP NOT NULL,
    ALTER COLUMN two_point_field_goals_made DROP NOT NULL,
    ALTER COLUMN three_point_field_goals_attempted DROP NOT NULL,
    ALTER COLUMN three_point_field_goals_made DROP NOT NULL,
    ALTER COLUMN free_throws_attempted DROP NOT NULL,
    ALTER COLUMN free_throws_made DROP NOT NULL,
    ALTER COLUMN rebounds_total DROP NOT NULL,
    ALTER COLUMN rebounds_defensive DROP NOT NULL,
    ALTER COLUMN rebounds_offensive DROP NOT NULL,
    ALTER COLUMN ppg DROP NOT NULL,
    ALTER COLUMN rpg DROP NOT NULL,
    ALTER COLUMN apg DROP NOT NULL,
    ALTER COLUMN tiebreaker_score DROP NOT NULL;

CREATE TABLE team_season_eligibility (
    team_id             INTEGER NOT NULL REFERENCES schools (id) ON DELETE CASCADE,
    season              SMALLINT NOT NULL,
    reasons             TEXT[] NOT NULL,
    first_poll_week     SMALLINT,
    first_poll_date     DATE,
    peak_rank           SMALLINT,
    qualified_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, season),
    CONSTRAINT team_season_eligibility_season_chk CHECK (season >= 2024),
    CONSTRAINT team_season_eligibility_reasons_chk CHECK (
        cardinality(reasons) > 0
        AND reasons <@ ARRAY['ap_top_25', 'virginia_tech']::TEXT[]
    ),
    CONSTRAINT team_season_eligibility_rank_chk CHECK (
        peak_rank IS NULL OR peak_rank BETWEEN 1 AND 25
    )
);

CREATE INDEX team_season_eligibility_season_idx
    ON team_season_eligibility (season, team_id);

CREATE TABLE player_seasons (
    id                                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id                           INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    team_id                             INTEGER NOT NULL REFERENCES schools (id) ON DELETE CASCADE,
    season                              SMALLINT NOT NULL,
    season_label                        TEXT,
    conference                          TEXT,
    athlete_source_id                   TEXT,
    source_position                     TEXT,
    games                               INTEGER,
    starts                              INTEGER,
    minutes                             INTEGER,
    points                              INTEGER,
    turnovers                           INTEGER,
    fouls                               INTEGER,
    assists                             INTEGER,
    steals                              INTEGER,
    blocks                              INTEGER,
    usage                               DOUBLE PRECISION,
    offensive_rating                    DOUBLE PRECISION,
    defensive_rating                    DOUBLE PRECISION,
    net_rating                          DOUBLE PRECISION,
    porpag                              DOUBLE PRECISION,
    effective_field_goal_pct            DOUBLE PRECISION,
    true_shooting_pct                   DOUBLE PRECISION,
    assists_turnover_ratio              DOUBLE PRECISION,
    free_throw_rate                     DOUBLE PRECISION,
    offensive_rebound_pct               DOUBLE PRECISION,
    field_goals_pct                     DOUBLE PRECISION,
    field_goals_attempted               INTEGER,
    field_goals_made                    INTEGER,
    two_point_field_goals_pct           DOUBLE PRECISION,
    two_point_field_goals_attempted     INTEGER,
    two_point_field_goals_made          INTEGER,
    three_point_field_goals_pct         DOUBLE PRECISION,
    three_point_field_goals_attempted   INTEGER,
    three_point_field_goals_made        INTEGER,
    free_throws_pct                     DOUBLE PRECISION,
    free_throws_attempted               INTEGER,
    free_throws_made                    INTEGER,
    rebounds_total                      INTEGER,
    rebounds_defensive                  INTEGER,
    rebounds_offensive                  INTEGER,
    win_shares_total_per40              DOUBLE PRECISION,
    win_shares_total                    DOUBLE PRECISION,
    win_shares_defensive                DOUBLE PRECISION,
    win_shares_offensive                DOUBLE PRECISION,
    torvik_id                           INTEGER,
    torvik_match_method                 TEXT,
    source_active                       BOOLEAN NOT NULL DEFAULT TRUE,
    source_updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT player_seasons_unique UNIQUE (player_id, team_id, season),
    CONSTRAINT player_seasons_season_chk CHECK (season BETWEEN 1900 AND 2100),
    CONSTRAINT player_seasons_torvik_fk
        FOREIGN KEY (torvik_id, season)
        REFERENCES player_defensive_stats (torvik_id, season)
);

CREATE INDEX player_seasons_team_season_idx
    ON player_seasons (team_id, season, source_active);
CREATE INDEX player_seasons_player_season_idx
    ON player_seasons (player_id, season);

INSERT INTO player_seasons (
    player_id, team_id, season, conference, athlete_source_id,
    games, starts, minutes, points, turnovers, fouls, assists, steals, blocks,
    usage, offensive_rating, defensive_rating, net_rating, porpag,
    effective_field_goal_pct, true_shooting_pct, assists_turnover_ratio,
    free_throw_rate, offensive_rebound_pct, field_goals_pct,
    field_goals_attempted, field_goals_made, two_point_field_goals_pct,
    two_point_field_goals_attempted, two_point_field_goals_made,
    three_point_field_goals_pct, three_point_field_goals_attempted,
    three_point_field_goals_made, free_throws_pct, free_throws_attempted,
    free_throws_made, rebounds_total, rebounds_defensive, rebounds_offensive,
    win_shares_total_per40, win_shares_total, win_shares_defensive,
    win_shares_offensive, torvik_id, torvik_match_method,
    source_active, source_updated_at
)
SELECT
    id, school_id, season, conference, athlete_source_id::TEXT,
    games, starts, minutes, points, turnovers, fouls, assists, steals, blocks,
    usage, offensive_rating, defensive_rating, net_rating, porpag,
    effective_field_goal_pct, true_shooting_pct, assists_turnover_ratio,
    free_throw_rate, offensive_rebound_pct, field_goals_pct,
    field_goals_attempted, field_goals_made, two_point_field_goals_pct,
    two_point_field_goals_attempted, two_point_field_goals_made,
    three_point_field_goals_pct, three_point_field_goals_attempted,
    three_point_field_goals_made, free_throws_pct, free_throws_attempted,
    free_throws_made, rebounds_total, rebounds_defensive, rebounds_offensive,
    win_shares_total_per40, win_shares_total, win_shares_defensive,
    win_shares_offensive, torvik_id, torvik_match_method,
    source_active, source_updated_at
FROM players
WHERE school_id IS NOT NULL AND season IS NOT NULL;

CREATE TABLE team_roster_memberships (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id           INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    team_id             INTEGER NOT NULL REFERENCES schools (id) ON DELETE CASCADE,
    season              SMALLINT NOT NULL,
    source_player_id    TEXT,
    jersey              TEXT,
    raw_position        TEXT,
    height              DOUBLE PRECISION,
    weight              DOUBLE PRECISION,
    date_of_birth       DATE,
    source_start_season SMALLINT,
    source_end_season   SMALLINT,
    source_active       BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT team_roster_memberships_unique
        UNIQUE (player_id, team_id, season),
    CONSTRAINT team_roster_memberships_season_chk CHECK (season >= 2024)
);

CREATE INDEX team_roster_memberships_team_season_idx
    ON team_roster_memberships (team_id, season, source_active);

CREATE TABLE team_roster_position_maps (
    roster_membership_id BIGINT NOT NULL
        REFERENCES team_roster_memberships (id) ON DELETE CASCADE,
    position             player_position NOT NULL,
    PRIMARY KEY (roster_membership_id, position)
);

CREATE TABLE college_games (
    id                  BIGINT PRIMARY KEY,
    source_id           TEXT NOT NULL,
    season              SMALLINT NOT NULL,
    season_type         TEXT NOT NULL,
    start_date          TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL,
    neutral_site        BOOLEAN NOT NULL DEFAULT FALSE,
    conference_game     BOOLEAN NOT NULL DEFAULT FALSE,
    home_team_id        INTEGER NOT NULL,
    home_team           TEXT NOT NULL,
    home_points         INTEGER,
    away_team_id        INTEGER NOT NULL,
    away_team           TEXT NOT NULL,
    away_points         INTEGER,
    raw_payload         JSONB NOT NULL,
    source_updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT college_games_season_chk CHECK (season >= 2024)
);

CREATE INDEX college_games_season_date_idx
    ON college_games (season, start_date);
CREATE INDEX college_games_home_team_idx
    ON college_games (home_team_id, season);
CREATE INDEX college_games_away_team_idx
    ON college_games (away_team_id, season);

CREATE TABLE team_game_lineups (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id             BIGINT NOT NULL REFERENCES college_games (id) ON DELETE CASCADE,
    team_id             INTEGER NOT NULL REFERENCES schools (id) ON DELETE CASCADE,
    season              SMALLINT NOT NULL,
    lineup_hash         TEXT NOT NULL,
    total_seconds       DOUBLE PRECISION NOT NULL,
    pace                DOUBLE PRECISION,
    offense_rating      DOUBLE PRECISION,
    defense_rating      DOUBLE PRECISION,
    net_rating          DOUBLE PRECISION,
    team_stats          JSONB NOT NULL,
    opponent_stats      JSONB NOT NULL,
    raw_payload         JSONB NOT NULL,
    source_updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT team_game_lineups_unique UNIQUE (game_id, team_id, lineup_hash),
    CONSTRAINT team_game_lineups_seconds_chk CHECK (total_seconds >= 0)
);

CREATE INDEX team_game_lineups_team_season_idx
    ON team_game_lineups (team_id, season);

CREATE TABLE team_game_lineup_players (
    lineup_id       BIGINT NOT NULL REFERENCES team_game_lineups (id) ON DELETE CASCADE,
    player_id       INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    ordinal         SMALLINT NOT NULL,
    PRIMARY KEY (lineup_id, player_id),
    CONSTRAINT team_game_lineup_players_ordinal_chk CHECK (ordinal BETWEEN 1 AND 5),
    CONSTRAINT team_game_lineup_players_lineup_ordinal_uniq UNIQUE (lineup_id, ordinal)
);

CREATE INDEX team_game_lineup_players_player_idx
    ON team_game_lineup_players (player_id, lineup_id);

CREATE TABLE opponent_team_season_contexts (
    team_id             INTEGER NOT NULL,
    season              SMALLINT NOT NULL,
    team                TEXT NOT NULL,
    games               INTEGER NOT NULL,
    pace                DOUBLE PRECISION,
    offense_rating      DOUBLE PRECISION,
    raw_payload         JSONB NOT NULL,
    source_updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, season)
);

CREATE TABLE defensive_model_versions (
    version         TEXT PRIMARY KEY,
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    configuration   JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at    TIMESTAMPTZ
);

CREATE UNIQUE INDEX defensive_model_versions_one_active_idx
    ON defensive_model_versions (is_active)
    WHERE is_active;

CREATE TABLE player_characteristic_scores (
    player_id           INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    team_id             INTEGER NOT NULL REFERENCES schools (id) ON DELETE CASCADE,
    season              SMALLINT NOT NULL,
    model_version       TEXT NOT NULL
        REFERENCES defensive_model_versions (version) ON DELETE CASCADE,
    characteristic_key  TEXT NOT NULL,
    score               DOUBLE PRECISION NOT NULL,
    confidence          DOUBLE PRECISION NOT NULL,
    qualified           BOOLEAN NOT NULL DEFAULT FALSE,
    games               INTEGER NOT NULL,
    possessions         DOUBLE PRECISION NOT NULL,
    data_through_date   DATE,
    evidence            JSONB NOT NULL,
    limitations         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (
        player_id, team_id, season, model_version, characteristic_key
    ),
    CONSTRAINT player_characteristic_scores_key_chk CHECK (
        characteristic_key IN (
            'RIM_PROTECTOR',
            'DEFENSIVE_GLASS_CLEANER',
            'DEFENSIVE_DISRUPTOR',
            'DROP_COMPATIBLE_BIG',
            'LIKELY_DROP_ANCHOR'
        )
    ),
    CONSTRAINT player_characteristic_scores_values_chk CHECK (
        score BETWEEN 0 AND 100
        AND confidence BETWEEN 0 AND 100
        AND games >= 0
        AND possessions >= 0
    )
);

CREATE INDEX player_characteristic_scores_lookup_idx
    ON player_characteristic_scores (
        team_id, season, model_version, characteristic_key, score DESC
    );
