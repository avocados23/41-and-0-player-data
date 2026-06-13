-- Positions are a junction so a player can hold more than one canonical
-- position (a generic source label like "G" expands to PG + SG). The
-- generic-to-canonical mapping lives in process_players.py.
CREATE TABLE player_position_maps (
    player_id INTEGER NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    position  player_position NOT NULL,
    PRIMARY KEY (player_id, position)
);

CREATE INDEX player_position_maps_position_idx ON player_position_maps (position);
