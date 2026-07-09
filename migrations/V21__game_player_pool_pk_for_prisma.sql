-- Repoint game_player_pool's primary key so `prisma db pull` can introspect the
-- draft-pick foreign key.
--
-- V18 shipped PK (game_id, player_id) plus a UNIQUE (game_id, player_id,
-- position) that the V19 draft-pick FK references. Because that unique is a
-- redundant superset of the (game_id, player_id) key, Prisma introspection drops
-- it and then fails to validate the FK (error P1012). Making (game_id,
-- player_id, position) the actual primary key removes the redundant constraint
-- while keeping the exact same guarantee the FK relied on: a pick may only
-- reference a pooled player at its pooled position.
--
-- Trade-off: the DB no longer forbids the same player occupying two positions in
-- one game's pool. That "distinct players across the pool" rule now lives in the
-- pool-generation query (which already owns the 4-per-position rule).

-- The FK depends on the constraint we are about to drop, so detach it first.
ALTER TABLE game_draft_picks
    DROP CONSTRAINT game_draft_picks_game_id_player_id_position_fkey;

-- Swap the pool's primary key from (game_id, player_id) to the 3-column slot key
-- and drop the now-redundant unique.
ALTER TABLE game_player_pool
    DROP CONSTRAINT game_player_pool_pkey;

ALTER TABLE game_player_pool
    DROP CONSTRAINT game_player_pool_game_id_player_id_position_key;

ALTER TABLE game_player_pool
    ADD PRIMARY KEY (game_id, player_id, position);

-- Recreate the draft-pick FK; it now references the new primary key.
ALTER TABLE game_draft_picks
    ADD CONSTRAINT game_draft_picks_game_id_player_id_position_fkey
        FOREIGN KEY (game_id, player_id, position)
        REFERENCES game_player_pool (game_id, player_id, position);
