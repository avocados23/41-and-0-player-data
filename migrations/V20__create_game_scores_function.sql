-- Sums each user's drafted lineup into a single hidden score. The per-player
-- score is 0.6 * porpag + 0.4 * dporpag; keeping it in SQL means the raw metric
-- never leaves the server, the aggregation is a single round trip, and the
-- winner rule has one source of truth. The verdict endpoint calls this and takes
-- the greater total (equal totals => tie).
--
-- The 0.6/0.4 weights are hardcoded here on purpose: retuning them is a
-- CREATE OR REPLACE FUNCTION migration, so no player rows are ever rewritten.
-- COALESCE guards the nullable anchors so a missing metric contributes 0 rather
-- than nulling the whole sum.
CREATE FUNCTION game_user_scores(p_game_id UUID)
RETURNS TABLE (user_id UUID, total_score DOUBLE PRECISION)
LANGUAGE sql STABLE AS $$
    SELECT dp.user_id,
           SUM(0.6 * COALESCE(p.porpag, 0) + 0.4 * COALESCE(p.dporpag, 0))
    FROM game_draft_picks dp
    JOIN players p ON p.id = dp.player_id
    WHERE dp.game_id = p_game_id
    GROUP BY dp.user_id;
$$;
