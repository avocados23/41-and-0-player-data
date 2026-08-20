-- Inspect the Torvik match, validate the values, then write the two anchor
-- metrics onto players.
--
-- Order of operations:
--   1. Flyway V10            -> creates player_defensive_stats
--   2. scripts/ingest/process_torvik_defensive_data.py -> populates player_defensive_stats
--   3. Flyway V11            -> adds players.dbpm, players.dporpag
--   4. Flyway V12            -> adds players.torvik_id, players.torvik_match_method
--   5. scripts/ingest/reconcile_torvik_ids.py -> matches players -> Torvik,
--      sets torvik_id + method
--   6. Sections 1-3 below    -> inspect the match and validate ranges
--   7. Section 4 (UPDATE)    -> write dbpm/dporpag onto players
--
-- After reconcile, the join is exact: players.(torvik_id, season) references
-- player_defensive_stats.(torvik_id, season). torvik_match_method records how
-- each row matched ('exact' / 'normalized' / 'name_season'); 'name_season' is
-- the team-agnostic fallback and is worth spot-checking.


-- ============================================================================
-- 1. INSPECT THE MATCH
-- ============================================================================

-- 1a. Coverage + method breakdown by season. Pre-2008 seasons have no Torvik
--     data (all unmatched) and that is expected.
SELECT
    season,
    COUNT(*)                                                   AS players,
    COUNT(*) FILTER (WHERE torvik_match_method = 'exact')      AS exact,
    COUNT(*) FILTER (WHERE torvik_match_method = 'normalized') AS normalized,
    COUNT(*) FILTER (WHERE torvik_match_method = 'name_season') AS name_season,
    COUNT(*) FILTER (WHERE torvik_id IS NULL)                  AS unmatched
FROM players
GROUP BY season
ORDER BY season;

-- 1b. Unmatched players that SHOULD have a Torvik row (season >= 2008).
--     These are the rows to inspect: spelling gaps, mid-season transfers, or
--     players Torvik genuinely lacks. (Same set as torvik_unmatched.csv.)
SELECT p.id AS player_id, p.name, s.name AS team, p.season
FROM players p
JOIN schools s ON s.id = p.school_id
WHERE p.season >= 2008
  AND p.torvik_id IS NULL
ORDER BY p.season DESC, p.name;

-- 1c. Team-agnostic fallback matches: matched by name+season while the school
--     name disagreed (e.g. Penn vs Pennsylvania). Spot-check these before
--     trusting them. (Same set as torvik_name_season_matches.csv.)
SELECT
    p.id AS player_id, p.name,
    s.name   AS players_team,
    pds.team AS torvik_team,
    p.season, p.torvik_id
FROM players p
JOIN schools s ON s.id = p.school_id
JOIN player_defensive_stats pds
  ON pds.torvik_id = p.torvik_id AND pds.season = p.season
WHERE p.torvik_match_method = 'name_season'
ORDER BY p.season DESC, p.name;


-- ============================================================================
-- 2. VALIDATE: confirm the values are in sane ranges (the per-game-sum bug is
--    gone). dbpm should be roughly -5..+10, dporpag roughly -2..+8.
--    Restricted to rows that actually map onto a player (the landing table also
--    holds deep-bench, low-minute seasons whose rate stats legitimately spike).
-- ============================================================================

-- 2a. Headline ranges for the player-seasons that map onto players.
SELECT
    MIN(pds.dbpm)    AS dbpm_min,    MAX(pds.dbpm)    AS dbpm_max,
    ROUND(AVG(pds.dbpm)::numeric, 3)    AS dbpm_avg,
    MIN(pds.dporpag) AS dporpag_min, MAX(pds.dporpag) AS dporpag_max,
    ROUND(AVG(pds.dporpag)::numeric, 3) AS dporpag_avg
FROM players p
JOIN player_defensive_stats pds
  ON pds.torvik_id = p.torvik_id AND pds.season = p.season;

-- 2b. Matched rows OUTSIDE the expected window -- inspect before trusting.
--     Expect 0 or a tiny tail; a flood means the parse/match is wrong.
SELECT p.id AS player_id, p.name, pds.season, pds.games, pds.dbpm, pds.dporpag, pds.drtg
FROM players p
JOIN player_defensive_stats pds
  ON pds.torvik_id = p.torvik_id AND pds.season = p.season
WHERE pds.dbpm    NOT BETWEEN -5 AND 10
   OR pds.dporpag NOT BETWEEN -2 AND 8
ORDER BY pds.season DESC, p.name;


-- ============================================================================
-- 3. PREVIEW the write-back count (should equal matched players in section 1).
-- ============================================================================
SELECT COUNT(*) AS rows_to_update
FROM players p
JOIN player_defensive_stats pds
  ON pds.torvik_id = p.torvik_id AND pds.season = p.season;


-- ============================================================================
-- 4. WRITE BACK: copy the two clean anchors onto players, joining on the exact
--    (torvik_id, season) key. Run only after sections 1-2 look right.
--    Offensive columns and the (now unused) corrupted defensive_rating /
--    net_rating columns are deliberately left untouched.
-- ============================================================================
BEGIN;

UPDATE players p
SET dbpm    = pds.dbpm,
    dporpag = pds.dporpag
FROM player_defensive_stats pds
WHERE pds.torvik_id = p.torvik_id
  AND pds.season    = p.season;

-- Verify the row count matches section 3 before committing. If not, ROLLBACK.
COMMIT;
