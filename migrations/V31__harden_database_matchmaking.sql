-- FIFO claims use this index for ORDER BY ... FOR UPDATE SKIP LOCKED.
CREATE INDEX game_player_queue_spots_fifo_idx
    ON game_player_queue_spots (joined_queue_timestamp, id);

-- Remove queue residue created by the former process-local matchmaker before
-- enforcing the database-backed lifecycle.
DELETE FROM game_player_queue_spots queue
USING games game
WHERE game.status = 'active'
  AND (game.user1_id = queue.user_id OR game.user2_id = queue.user_id);

-- The queue transaction prevents duplicate claims, while this trigger is the
-- final invariant for every game writer. Advisory locks serialize transactions
-- that overlap on either user even though the users occupy two columns.
CREATE FUNCTION enforce_one_active_game_per_user()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    first_user TEXT;
    second_user TEXT;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    first_user := LEAST(NEW.user1_id::text, NEW.user2_id::text);
    second_user := GREATEST(NEW.user1_id::text, NEW.user2_id::text);
    PERFORM pg_advisory_xact_lock(hashtextextended(first_user, 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(second_user, 0));

    IF EXISTS (
        SELECT 1
        FROM games existing
        WHERE existing.status = 'active'
          AND existing.id <> NEW.id
          AND (
              existing.user1_id IN (NEW.user1_id, NEW.user2_id)
              OR existing.user2_id IN (NEW.user1_id, NEW.user2_id)
          )
    ) THEN
        RAISE EXCEPTION 'A user cannot participate in more than one active game'
            USING ERRCODE = 'unique_violation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER games_one_active_game_per_user_trigger
BEFORE INSERT OR UPDATE OF user1_id, user2_id, status
ON games
FOR EACH ROW
EXECUTE FUNCTION enforce_one_active_game_per_user();
