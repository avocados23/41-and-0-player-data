DO $$
DECLARE
    current_version INTEGER;
    queued_users INTEGER;
    active_users_queued INTEGER;
BEGIN
    SELECT MAX(version::INTEGER) INTO current_version
    FROM flyway_schema_history
    WHERE success;
    IF current_version <> 31 THEN
        RAISE EXCEPTION 'Expected schema version 31, got %', current_version;
    END IF;

    IF to_regclass('public.data_import_runs') IS NULL THEN
        RAISE EXCEPTION 'data_import_runs was not created';
    END IF;

    SELECT COUNT(*) INTO queued_users FROM game_player_queue_spots;
    IF queued_users <> 1 THEN
        RAISE EXCEPTION 'Expected one non-matched queue row, got %', queued_users;
    END IF;

    SELECT COUNT(*) INTO active_users_queued
    FROM game_player_queue_spots queue
    JOIN games game
      ON game.status = 'active'
     AND (game.user1_id = queue.user_id OR game.user2_id = queue.user_id);
    IF active_users_queued <> 0 THEN
        RAISE EXCEPTION 'Active users remained queued after V31';
    END IF;

    BEGIN
        INSERT INTO games (user1_id, user2_id, current_turn_user_id) VALUES (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000003',
            '00000000-0000-0000-0000-000000000001'
        );
        RAISE EXCEPTION 'Overlapping active game was incorrectly accepted';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;
END
$$;
