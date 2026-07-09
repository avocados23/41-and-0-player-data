-- Replace the composite draft-pick -> pool foreign key with a single-column one,
-- so `prisma db pull` produces a valid, stable schema.
--
-- Background: V21 made (game_id, player_id, position) the pool's primary key and
-- had game_draft_picks reference it with a 3-column composite FK. Prisma's
-- introspection cannot model a composite FK that targets a composite PK in this
-- shape -- it always emits a one-to-one relation and then rejects its own output
-- (P1012) for lacking an explicit @@unique it also won't generate. No arrangement
-- of constraints fixes it; the composite FK has to go.
--
-- Fix: give game_player_pool a single-column surrogate id (the same pattern
-- player_position_maps uses) and have game_draft_picks reference it via a single
-- pool_id column. The (game_id, player_id, position) slot key is kept as a plain
-- unique so pool slots stay distinct.
--
-- Trade-off: the DB no longer enforces that a pick's position matches its pooled
-- player's position. That becomes an app-level invariant -- the draft endpoint
-- copies player_id and position from the chosen pool slot (identified by pool_id)
-- when inserting a pick.
--
-- NOTE: assumes game_draft_picks is empty (pre-launch); pool_id is added NOT NULL
-- with no backfill, so the migration fails loudly if picks already exist.

-- Detach the composite FK before reshaping the pool's primary key.
ALTER TABLE game_draft_picks
    DROP CONSTRAINT game_draft_picks_game_id_player_id_position_fkey;

-- Swap the pool's primary key to a single-column surrogate id; keep the slot
-- (game_id, player_id, position) as a plain unique.
ALTER TABLE game_player_pool
    DROP CONSTRAINT game_player_pool_pkey;

ALTER TABLE game_player_pool
    ADD COLUMN id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY;

ALTER TABLE game_player_pool
    ADD CONSTRAINT game_player_pool_slot_key UNIQUE (game_id, player_id, position);

-- Draft picks now reference a pool slot by its surrogate id (single-column FK).
ALTER TABLE game_draft_picks
    ADD COLUMN pool_id BIGINT NOT NULL REFERENCES game_player_pool (id) ON DELETE CASCADE;
