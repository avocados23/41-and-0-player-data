-- Loads the processed CSVs into bracketballer_dev. Run from the project root:
--   PGPASSWORD=test psql -h localhost -U postgres -d bracketballer_dev -v ON_ERROR_STOP=1 -f load_data.sql
--
-- Idempotent: truncates the three data tables first, so it can be re-run after
-- regenerating the CSVs. schools must load before players (FK), and players
-- before player_position_maps (FK).

BEGIN;

TRUNCATE schools, players, player_position_maps RESTART IDENTITY CASCADE;

-- schools.csv is (id, name), matching the table exactly.
\copy schools (id, name) FROM 'schools.csv' WITH (FORMAT csv, HEADER true)

-- processed_players.csv carries extra columns and source (camelCase) names, so
-- stage it as-is (columns in CSV order), then project into players. Empty CSV
-- fields become NULL under FORMAT csv, which is fine for the nullable metrics.
CREATE TEMP TABLE players_staging (
    season                            INTEGER,
    season_label                      TEXT,
    team_id                           INTEGER,
    team                              TEXT,
    conference                        TEXT,
    athlete_id                        INTEGER,
    athlete_source_id                 BIGINT,
    name                              TEXT,
    position                          TEXT,
    games                             INTEGER,
    starts                            INTEGER,
    minutes                           INTEGER,
    points                            INTEGER,
    turnovers                         INTEGER,
    fouls                             INTEGER,
    assists                           INTEGER,
    steals                            INTEGER,
    blocks                            INTEGER,
    usage                             DOUBLE PRECISION,
    offensive_rating                  DOUBLE PRECISION,
    porpag                            DOUBLE PRECISION,
    effective_field_goal_pct          DOUBLE PRECISION,
    true_shooting_pct                 DOUBLE PRECISION,
    assists_turnover_ratio            DOUBLE PRECISION,
    free_throw_rate                   DOUBLE PRECISION,
    offensive_rebound_pct             DOUBLE PRECISION,
    field_goals_pct                   DOUBLE PRECISION,
    field_goals_attempted             INTEGER,
    field_goals_made                  INTEGER,
    two_point_field_goals_pct         DOUBLE PRECISION,
    two_point_field_goals_attempted   INTEGER,
    two_point_field_goals_made        INTEGER,
    three_point_field_goals_pct       DOUBLE PRECISION,
    three_point_field_goals_attempted INTEGER,
    three_point_field_goals_made      INTEGER,
    free_throws_pct                   DOUBLE PRECISION,
    free_throws_attempted             INTEGER,
    free_throws_made                  INTEGER,
    rebounds_total                    INTEGER,
    rebounds_defensive                INTEGER,
    rebounds_offensive                INTEGER,
    win_shares_total_per40            DOUBLE PRECISION,
    win_shares_total                  DOUBLE PRECISION,
    win_shares_defensive              DOUBLE PRECISION,
    win_shares_offensive              DOUBLE PRECISION,
    defensive_rating                  DOUBLE PRECISION,
    net_rating                        DOUBLE PRECISION,
    ppg                               DOUBLE PRECISION,
    rpg                               DOUBLE PRECISION,
    apg                               DOUBLE PRECISION,
    tiebreaker_score                  DOUBLE PRECISION
);

\copy players_staging FROM 'processed_players.csv' WITH (FORMAT csv, HEADER true)

INSERT INTO players (
    id, athlete_source_id, name, school_id, conference, season,
    games, starts, minutes, points, turnovers, fouls, assists, steals, blocks,
    usage, offensive_rating, defensive_rating, net_rating, porpag,
    effective_field_goal_pct, true_shooting_pct, assists_turnover_ratio,
    free_throw_rate, offensive_rebound_pct,
    field_goals_pct, field_goals_attempted, field_goals_made,
    two_point_field_goals_pct, two_point_field_goals_attempted, two_point_field_goals_made,
    three_point_field_goals_pct, three_point_field_goals_attempted, three_point_field_goals_made,
    free_throws_pct, free_throws_attempted, free_throws_made,
    rebounds_total, rebounds_defensive, rebounds_offensive,
    win_shares_total_per40, win_shares_total, win_shares_defensive, win_shares_offensive,
    ppg, rpg, apg, tiebreaker_score
)
SELECT
    athlete_id, athlete_source_id, name, team_id, conference, season,
    games, starts, minutes, points, turnovers, fouls, assists, steals, blocks,
    usage, offensive_rating, defensive_rating, net_rating, porpag,
    effective_field_goal_pct, true_shooting_pct, assists_turnover_ratio,
    free_throw_rate, offensive_rebound_pct,
    field_goals_pct, field_goals_attempted, field_goals_made,
    two_point_field_goals_pct, two_point_field_goals_attempted, two_point_field_goals_made,
    three_point_field_goals_pct, three_point_field_goals_attempted, three_point_field_goals_made,
    free_throws_pct, free_throws_attempted, free_throws_made,
    rebounds_total, rebounds_defensive, rebounds_offensive,
    win_shares_total_per40, win_shares_total, win_shares_defensive, win_shares_offensive,
    ppg, rpg, apg, tiebreaker_score
FROM players_staging;

-- player_positions.csv is (player_id, position); text casts to the enum.
\copy player_position_maps (player_id, position) FROM 'player_positions.csv' WITH (FORMAT csv, HEADER true)

COMMIT;
