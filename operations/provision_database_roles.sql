-- Run once as the managed-database owner after Flyway has applied all
-- migrations. These are NOLOGIN group roles: create/rotate login users in the
-- provider control plane, then grant each user exactly one group role.
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -f operations/provision_database_roles.sql

BEGIN;

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bracketballer_app') THEN
        CREATE ROLE bracketballer_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bracketballer_ingest') THEN
        CREATE ROLE bracketballer_ingest NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bracketballer_readonly') THEN
        CREATE ROLE bracketballer_readonly NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
END
$roles$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO bracketballer_app, bracketballer_ingest, bracketballer_readonly;

-- Runtime application: normal API transactions, never DDL or release-audit
-- mutation. Explicit revokes keep this true when broad grants are refreshed.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO bracketballer_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO bracketballer_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON data_import_runs FROM bracketballer_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON flyway_schema_history FROM bracketballer_app;

-- Ingestion can update sports/model data and its audit rows, but cannot touch
-- accounts, games, or community content.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bracketballer_ingest;
GRANT INSERT, UPDATE, DELETE ON
    schools,
    players,
    player_position_maps,
    player_defensive_stats,
    player_shot_events,
    player_shooting_ingestion_status,
    player_shooting_profiles,
    shooting_model_versions,
    player_shooting_ability_profiles,
    player_shooting_zone_profiles,
    player_shooting_game_profiles,
    player_contextual_shooting_profiles,
    data_import_runs
TO bracketballer_ingest;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO bracketballer_ingest;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO bracketballer_readonly;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO bracketballer_readonly;

-- Flyway runs as the bracketballer_migrator owner, so these defaults cover future objects it
-- creates. New ingestion write targets still require an explicit reviewed
-- grant above; least privilege must not silently expand with the schema.
ALTER DEFAULT PRIVILEGES FOR ROLE bracketballer_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO bracketballer_app;
ALTER DEFAULT PRIVILEGES FOR ROLE bracketballer_migrator IN SCHEMA public
    GRANT SELECT ON TABLES TO bracketballer_ingest, bracketballer_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE bracketballer_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO bracketballer_app, bracketballer_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE bracketballer_migrator IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO bracketballer_readonly;

COMMIT;
