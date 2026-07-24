-- The community "labels" dictionary: named interpretations of a lineup that are
-- grounded in the raw signals produced by the shooting model. Ownership of
-- interpretation moves from the app to users -- the app no longer hard-codes
-- verdict copy; instead these rows (seed + user-authored) are the shared
-- vocabulary the community votes on and reuses.
--
-- signal_claims is the label's falsifiable assertion about the lineup: a JSON
-- array of {signal_key, expected_band} objects (band in negative|neutral|
-- positive). Voters judge how accurately a label's claims match the frozen
-- signals of the lineup it is applied to (see published_lineups, V29).
--
-- author_user_id NULL marks a system seed (is_seed = true). The check keeps the
-- two in lockstep: seeds have no author, user labels always do.
CREATE TABLE lineup_labels (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    author_user_id UUID REFERENCES users (id) ON DELETE CASCADE,
    is_seed        BOOLEAN NOT NULL DEFAULT false,
    title          TEXT NOT NULL,
    rationale      TEXT,
    category       TEXT NOT NULL,
    signal_claims  JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT lineup_labels_category_chk
        CHECK (category IN ('spacing', 'defense', 'offense', 'clutch')),
    CONSTRAINT lineup_labels_author_chk
        CHECK (
            (is_seed AND author_user_id IS NULL)
            OR (NOT is_seed AND author_user_id IS NOT NULL)
        )
);

CREATE INDEX lineup_labels_claims_idx   ON lineup_labels USING GIN (signal_claims);
CREATE INDEX lineup_labels_category_idx ON lineup_labels (category);
CREATE INDEX lineup_labels_seed_idx     ON lineup_labels (is_seed);

-- Seed vocabulary migrated from the app's former editorial copy
-- (LINEUP_ASSESSMENT_PRESENTATION + CRITICAL_LINEUP_SIGNAL_LABELS), re-expressed
-- as signal-grounded claims so new users have a starting corpus to react to.
-- The three negative critical-signal phrases are preserved verbatim; positive
-- exemplars are added so each category shows both directions.
INSERT INTO lineup_labels (is_seed, title, rationale, category, signal_claims) VALUES
    (
        true,
        'Poor floor spacing',
        'Not enough perimeter gravity to keep the paint open; drivers and post play get crowded.',
        'spacing',
        '[{"signal_key": "spacing", "expected_band": "negative"}]'::jsonb
    ),
    (
        true,
        'Five-out spacing',
        'Shooting at every position stretches the defense and opens driving lanes.',
        'spacing',
        '[{"signal_key": "spacing", "expected_band": "positive"}, {"signal_key": "three_level_coverage", "expected_band": "positive"}]'::jsonb
    ),
    (
        true,
        'No reliable primary and secondary ball handlers',
        'Without dependable initiators the offense stalls against pressure and late in the clock.',
        'offense',
        '[{"signal_key": "creator_coverage", "expected_band": "negative"}]'::jsonb
    ),
    (
        true,
        'Weak ball movement',
        'The ball sticks; too little passing to bend the defense and find the extra pass.',
        'offense',
        '[{"signal_key": "ball_movement", "expected_band": "negative"}]'::jsonb
    ),
    (
        true,
        'Downhill shot creation',
        'Multiple on-ball creators who pressure the rim and collapse the defense.',
        'offense',
        '[{"signal_key": "shot_creation", "expected_band": "positive"}, {"signal_key": "rim_pressure", "expected_band": "positive"}]'::jsonb
    ),
    (
        true,
        'Switch-everything defense',
        'Rim protection plus perimeter disruption lets this group guard multiple actions.',
        'defense',
        '[{"signal_key": "rim_protection", "expected_band": "positive"}, {"signal_key": "defensive_disruption", "expected_band": "positive"}]'::jsonb
    ),
    (
        true,
        'Reliable in the clutch',
        'Shot creation and free-throw pressure to close out tight games.',
        'clutch',
        '[{"signal_key": "shot_creation", "expected_band": "positive"}, {"signal_key": "free_throw_pressure", "expected_band": "positive"}]'::jsonb
    );
