-- One row per head-to-head game between two users. Turn/timer state lives here:
-- current_turn_user_id is whoever must pick next, and turn_deadline is the 60s
-- cutoff that the app uses to trigger an auto-pick. winner_user_id is written at
-- finish time from game_user_scores (V20); NULL means a tie or an unfinished game.
CREATE TABLE games (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user1_id             UUID NOT NULL REFERENCES users (id),
    user2_id             UUID NOT NULL REFERENCES users (id),
    status               game_status NOT NULL DEFAULT 'active',
    current_turn_user_id UUID REFERENCES users (id),   -- whose pick it is
    turn_deadline        TIMESTAMPTZ,                   -- now()+60s each turn; drives auto-pick
    winner_user_id       UUID REFERENCES users (id),    -- NULL = tie or unfinished
    started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at          TIMESTAMPTZ,
    CHECK (user1_id <> user2_id)
);

-- A user may be in at most one active game at a time. Postgres can't express a
-- single uniqueness rule across the two user columns, so the create-game
-- transaction checks both columns; these partial indexes make that lookup cheap.
CREATE INDEX games_user1_active_idx ON games (user1_id) WHERE status = 'active';
CREATE INDEX games_user2_active_idx ON games (user2_id) WHERE status = 'active';
