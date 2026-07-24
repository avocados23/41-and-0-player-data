-- A published lineup is the votable unit of community intelligence: a concrete
-- five, a frozen snapshot of the signals the server computed for it, and the
-- label a user applied. The signals are frozen at publish time (server-computed,
-- never client-supplied) so votes judge the label against an authoritative,
-- tamper-proof reading of the lineup even as the model version advances.
--
--   lineup           -- [{player_id, position} x5], one per position
--   signals_snapshot -- frozen LineupSignalsAnalysis (assessment + signals[])
--   model_version    -- the shooting model version that produced the snapshot
--
-- label_id uses ON DELETE RESTRICT: a label that has been applied to a published
-- lineup cannot be deleted out from under it (unlike per-user rows, which cascade).
CREATE TABLE published_lineups (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    author_user_id   UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    label_id         UUID NOT NULL REFERENCES lineup_labels (id) ON DELETE RESTRICT,
    lineup           JSONB NOT NULL,
    signals_snapshot JSONB NOT NULL,
    model_version    TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX published_lineups_author_idx  ON published_lineups (author_user_id);
CREATE INDEX published_lineups_label_idx   ON published_lineups (label_id);
CREATE INDEX published_lineups_created_idx ON published_lineups (created_at DESC);

-- One vote per user per published lineup (PK enforces it). value is strictly
-- -1 or +1; "no vote" is the absence of a row, so toggling a vote off deletes it.
CREATE TABLE lineup_votes (
    published_lineup_id UUID NOT NULL REFERENCES published_lineups (id) ON DELETE CASCADE,
    user_id             UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    value               SMALLINT NOT NULL CHECK (value IN (-1, 1)),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (published_lineup_id, user_id)
);

-- Flat comments in v1 (a parent_id column can add threading later).
CREATE TABLE lineup_comments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    published_lineup_id UUID NOT NULL REFERENCES published_lineups (id) ON DELETE CASCADE,
    author_user_id      UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    body                TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT lineup_comments_body_chk CHECK (length(btrim(body)) > 0)
);

CREATE INDEX lineup_comments_lineup_idx ON lineup_comments (published_lineup_id, created_at);
