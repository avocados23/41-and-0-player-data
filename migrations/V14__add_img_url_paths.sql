-- add image path URL for players
ALTER TABLE players
    ADD COLUMN player_headshot_img TEXT;

-- add image path URL for schools
ALTER TABLE schools
    ADD COLUMN school_logo_img TEXT;
    