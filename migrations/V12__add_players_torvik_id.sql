-- Give players a stable Torvik join key. players was sourced from CBBD and has
-- no Torvik id, so the (name, team, season) join is fragile across the two
-- sources' spellings. reconcile_torvik_ids.py does the normalized matching once
-- and writes torvik_id here; everything downstream then joins on (torvik_id,
-- season), which is exact. torvik_match_method records HOW each row matched so
-- the team-agnostic fallback rows can be spot-checked.
ALTER TABLE players
    ADD COLUMN torvik_id           INTEGER,
    ADD COLUMN torvik_match_method TEXT
        CONSTRAINT players_torvik_match_method_chk
        CHECK (torvik_match_method IN ('exact', 'normalized', 'name_season'));

-- (torvik_id, season) points at exactly one Torvik player-season. NULL torvik_id
-- (unmatched players, incl. all pre-2008) skips the check under MATCH SIMPLE.
ALTER TABLE players
    ADD CONSTRAINT players_torvik_fk
    FOREIGN KEY (torvik_id, season)
    REFERENCES player_defensive_stats (torvik_id, season);

CREATE INDEX players_torvik_id_season_idx ON players (torvik_id, season);
