CREATE TABLE saved_labels (
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    label_id UUID NOT NULL REFERENCES lineup_labels (id) ON DELETE CASCADE,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_user_id ON saved_labels(user_id);