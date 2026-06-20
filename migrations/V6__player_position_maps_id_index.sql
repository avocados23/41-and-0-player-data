-- Add a single-column surrogate id to player_position_maps as a secondary
-- index. The composite (player_id, position) remains the primary key; the id
-- just gives a single-column handle for referencing rows.
ALTER TABLE player_position_maps
    ADD COLUMN id INTEGER GENERATED ALWAYS AS IDENTITY;

CREATE UNIQUE INDEX player_position_maps_id_idx ON player_position_maps (id);
