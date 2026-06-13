-- One row per athlete: their best D1 season (highest PPG, ties broken by
-- PPG + RPG + APG). Stats are season totals from that season. Positions live
-- in the player_position_maps junction table (a player can hold more than one).
CREATE TABLE players (
    id                                INTEGER PRIMARY KEY,  -- source athleteId
    athlete_source_id                 BIGINT,
    name                              TEXT NOT NULL,
    school_id                         INTEGER NOT NULL REFERENCES schools (id),
    conference                        TEXT NOT NULL,
    season                            INTEGER NOT NULL,     -- ending year, e.g. 2025 = 2024-25

    games                             INTEGER NOT NULL,
    starts                            INTEGER NOT NULL,
    minutes                           INTEGER NOT NULL,
    points                            INTEGER NOT NULL,
    turnovers                         INTEGER NOT NULL,
    fouls                             INTEGER NOT NULL,
    assists                           INTEGER NOT NULL,
    steals                            INTEGER NOT NULL,
    blocks                            INTEGER NOT NULL,

    usage                             DOUBLE PRECISION,
    offensive_rating                  DOUBLE PRECISION,
    defensive_rating                  DOUBLE PRECISION,
    net_rating                        DOUBLE PRECISION,
    porpag                            DOUBLE PRECISION,
    effective_field_goal_pct          DOUBLE PRECISION,
    true_shooting_pct                 DOUBLE PRECISION,
    assists_turnover_ratio            DOUBLE PRECISION,
    free_throw_rate                   DOUBLE PRECISION,
    offensive_rebound_pct             DOUBLE PRECISION,

    field_goals_pct                   DOUBLE PRECISION,
    field_goals_attempted             INTEGER NOT NULL,
    field_goals_made                  INTEGER NOT NULL,
    two_point_field_goals_pct         DOUBLE PRECISION,
    two_point_field_goals_attempted   INTEGER NOT NULL,
    two_point_field_goals_made        INTEGER NOT NULL,
    three_point_field_goals_pct       DOUBLE PRECISION,
    three_point_field_goals_attempted INTEGER NOT NULL,
    three_point_field_goals_made      INTEGER NOT NULL,
    free_throws_pct                   DOUBLE PRECISION,
    free_throws_attempted             INTEGER NOT NULL,
    free_throws_made                  INTEGER NOT NULL,

    rebounds_total                    INTEGER NOT NULL,
    rebounds_defensive                INTEGER NOT NULL,
    rebounds_offensive                INTEGER NOT NULL,

    win_shares_total_per40            DOUBLE PRECISION,
    win_shares_total                  DOUBLE PRECISION,
    win_shares_defensive              DOUBLE PRECISION,
    win_shares_offensive              DOUBLE PRECISION,

    ppg                               DOUBLE PRECISION NOT NULL,
    rpg                               DOUBLE PRECISION NOT NULL,
    apg                               DOUBLE PRECISION NOT NULL,
    tiebreaker_score                  DOUBLE PRECISION NOT NULL
);

CREATE INDEX players_school_id_idx ON players (school_id);
