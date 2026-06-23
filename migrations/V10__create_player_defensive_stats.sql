-- Clean defensive stats sourced from Bart Torvik's bulk player advanced feed.
-- One row per Torvik player-season. This is a landing table: process_torvik_
-- defensive_data.py upserts into it, then we join it onto players by
-- (name, team, season) and write the two anchor metrics back to players.
-- Kept separate from players so the raw Torvik id/spelling survives for re-joins.
CREATE TABLE player_defensive_stats (
    id          BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    torvik_id   INTEGER      NOT NULL,            -- Torvik player id (join key for re-runs)
    player      TEXT         NOT NULL,            -- player name (Torvik spelling)
    team        TEXT         NOT NULL,            -- school name (Torvik spelling)
    conf        TEXT,                             -- conference
    season      SMALLINT     NOT NULL,            -- ending year, e.g. 2023 for 2022-23

    games       SMALLINT,                         -- games played

    dporpag     DOUBLE PRECISION,                 -- defensive PORPAG (primary anchor)
    dbpm        DOUBLE PRECISION,                 -- defensive box plus/minus (secondary anchor)
    drtg        DOUBLE PRECISION,                 -- defensive rating (sanity check only, not scored)
    blk_pct     DOUBLE PRECISION,                 -- block rate
    stl_pct     DOUBLE PRECISION,                 -- steal rate
    dr_pct      DOUBLE PRECISION,                 -- defensive rebound rate

    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT player_defensive_stats_torvik_season_uniq UNIQUE (torvik_id, season),
    CONSTRAINT player_defensive_stats_season_chk         CHECK (season BETWEEN 1900 AND 2100)
);

-- The join onto players is by (name, team, season); index those lookups.
CREATE INDEX player_defensive_stats_name_team_season_idx
    ON player_defensive_stats (player, team, season);
