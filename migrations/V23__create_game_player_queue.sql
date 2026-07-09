CREATE TABLE game_player_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    joined_queue_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id)
);