ALTER TABLE users
    ADD last_logged_in_at TIMESTAMPTZ NOT NULL DEFAULT now();