-- Lifecycle states for a game: 'active' while drafting is in progress,
-- 'finished' once all ten picks are in and a verdict has been recorded, and
-- 'abandoned' for games ended early. Only 'active' games count toward the
-- one-game-at-a-time rule (see the partial indexes in V17).
CREATE TYPE game_status AS ENUM (
    'active',
    'finished',
    'abandoned'
);
