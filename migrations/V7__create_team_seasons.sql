CREATE TABLE team_seasons (
    id                    BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_id               BIGINT       NOT NULL REFERENCES schools (id) ON DELETE CASCADE,
    season                SMALLINT     NOT NULL,            -- ending year, e.g. 2023 for the 2022-23 season
    strength_of_schedule  NUMERIC(6,3) NOT NULL,            -- raw SRS-style SOS (decimal, can be negative); sos_pct is derived
    wins                  SMALLINT,                         -- optional: not a stud-factor input, kept for other components/display
    losses                SMALLINT,
    games_played          SMALLINT     GENERATED ALWAYS AS (wins + losses) STORED,  -- derived; never written directly
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT team_seasons_team_season_uniq UNIQUE (team_id, season),
    CONSTRAINT team_seasons_season_chk       CHECK (season BETWEEN 1900 AND 2100),
    CONSTRAINT team_seasons_record_chk       CHECK (wins >= 0 AND losses >= 0)
);

-- Supports the within-season percentile the formula reads as sos_pct:
--   percent_rank() OVER (PARTITION BY season ORDER BY strength_of_schedule ASC)
CREATE INDEX team_seasons_season_sos_idx
    ON team_seasons (season, strength_of_schedule);