-- The fixed draft pool for a game: 4 players per position, 20 rows per game,
-- chosen randomly at game creation. Both users draft from this shared pool. The
-- primary key stops a multi-position player from appearing twice in the same
-- game, and the (game_id, player_id, position) unique key is the target for the
-- draft-pick foreign key in V19, which pins a pick to a pooled player at its
-- assigned position.
CREATE TABLE game_player_pool (
    game_id   UUID NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players (id),
    position  player_position NOT NULL,
    PRIMARY KEY (game_id, player_id),
    UNIQUE (game_id, player_id, position)
);

-- The draft UI and the timer auto-pick both list a game's candidates by position.
CREATE INDEX game_player_pool_game_position_idx ON game_player_pool (game_id, position);
