-- Add the two clean defensive anchor metrics to players. These are populated
-- from player_defensive_stats (Bart Torvik) by the UPDATE in
-- process_torvik_defensive_data.sql, once the join has been validated.
-- The corrupted CBBD columns (defensive_rating, net_rating) are left in place
-- and simply no longer used for scoring. Offensive columns are untouched.
ALTER TABLE players
    ADD COLUMN dbpm    DOUBLE PRECISION,   -- defensive box plus/minus (secondary anchor)
    ADD COLUMN dporpag DOUBLE PRECISION;   -- defensive PORPAG (primary anchor)
