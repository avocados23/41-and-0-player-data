-- Widen the allowed torvik_match_method values. V12 only permitted
-- exact/normalized/name_season; reconcile_torvik_ids.py now also resolves
-- players via same-school fuzzy and surname matching, plus a small hand-verified
-- override list, and records which tier matched each row so they stay auditable.
ALTER TABLE players
    DROP CONSTRAINT players_torvik_match_method_chk;

ALTER TABLE players
    ADD CONSTRAINT players_torvik_match_method_chk
    CHECK (torvik_match_method IN (
        'exact',         -- raw (name, team, season) identical
        'normalized',    -- normalized (name, team, season) agree
        'team_fuzzy',    -- same school+season, fuzzy name match
        'team_surname',  -- same school+season, unique exact surname
        'name_season',   -- unique normalized name in season (team-agnostic)
        'manual'         -- hand-verified override (nickname / name change / order swap)
    ));
