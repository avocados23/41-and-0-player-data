-- One row per drafted player. user_id records which of the two players made the
-- pick, which is what lets game_user_scores (V20) sum each side separately.
-- was_auto_pick flags picks the 60s timer made on the user's behalf.
--
-- Three constraints enforce the draft rules in the database:
--   * UNIQUE (game_id, user_id, position) -- a user fills each position at most once
--   * UNIQUE (game_id, player_id)          -- a shared-pool player is drafted only once
--   * FK to game_player_pool               -- a pick must be a pooled player at its pool position
CREATE TABLE game_draft_picks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id       UUID NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES users (id),
    player_id     INTEGER NOT NULL REFERENCES players (id),
    position      player_position NOT NULL,
    was_auto_pick BOOLEAN NOT NULL DEFAULT false,
    picked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (game_id, user_id, position),
    UNIQUE (game_id, player_id),
    FOREIGN KEY (game_id, player_id, position)
        REFERENCES game_player_pool (game_id, player_id, position)
);
