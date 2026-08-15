-- V33 created saved_labels with no primary key or unique constraint on
-- (user_id, label_id), only a plain index on user_id. The save-label upsert
-- (INSERT ... ON CONFLICT (user_id, label_id) DO NOTHING) requires a real
-- unique/exclusion constraint matching that conflict target; without one,
-- Postgres rejects the query with 42P10.
--
-- Fix: make (user_id, label_id) the table's primary key -- each user can
-- save each label at most once, so this is the table's natural identity,
-- and it gives the upsert the constraint it needs. The separate idx_user_id
-- index becomes redundant once (user_id, label_id) is the primary key: a
-- composite index's leading column already supports equality lookups on
-- user_id alone, so it is dropped.

DROP INDEX idx_user_id;

ALTER TABLE saved_labels
    ADD PRIMARY KEY (user_id, label_id);
