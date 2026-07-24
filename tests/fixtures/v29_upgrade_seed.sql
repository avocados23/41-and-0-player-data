INSERT INTO users (id, clerk_user_id, email, display_name) VALUES
    ('00000000-0000-0000-0000-000000000001', 'upgrade-1', 'upgrade-1@example.com', 'upgrade-1'),
    ('00000000-0000-0000-0000-000000000002', 'upgrade-2', 'upgrade-2@example.com', 'upgrade-2'),
    ('00000000-0000-0000-0000-000000000003', 'upgrade-3', 'upgrade-3@example.com', 'upgrade-3');

INSERT INTO games (
    id, user1_id, user2_id, current_turn_user_id
) VALUES (
    '10000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000001'
);

INSERT INTO game_player_queue_spots (user_id) VALUES
    ('00000000-0000-0000-0000-000000000001'),
    ('00000000-0000-0000-0000-000000000002'),
    ('00000000-0000-0000-0000-000000000003');
