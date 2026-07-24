-- Capture with:
--   psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
--     -f operations/database_manifest.sql > manifest.txt
-- Run under a repeatable-read, read-only transaction for a consistent view.

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

SELECT 'flyway' AS section, version, description, checksum, success
FROM flyway_schema_history
ORDER BY installed_rank;

SELECT format(
    'SELECT %L AS section, %L AS table_name, COUNT(*)::bigint AS row_count FROM %I.%I;',
    'table_count', schemaname || '.' || tablename, schemaname, tablename
)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename <> 'flyway_schema_history'
ORDER BY tablename
\gexec

SELECT 'players_by_season' AS section, season::text AS key, COUNT(*)::bigint AS value
FROM players
GROUP BY season
ORDER BY season;

SELECT 'shots_by_season' AS section, season::text AS key, COUNT(*)::bigint AS value
FROM player_shot_events
GROUP BY season
ORDER BY season;

SELECT 'models' AS section, version AS key, is_active::text AS active,
       (SELECT COUNT(*) FROM player_shooting_ability_profiles profile
        WHERE profile.model_version = model.version) AS ability_profiles,
       (SELECT COUNT(*) FROM player_contextual_shooting_profiles profile
        WHERE profile.model_version = model.version) AS contextual_profiles
FROM shooting_model_versions model
ORDER BY version;

SELECT 'schema_objects' AS section,
       (SELECT COUNT(*) FROM pg_constraint WHERE connamespace = 'public'::regnamespace) AS constraints,
       (SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'public') AS indexes,
       (SELECT COUNT(*) FROM pg_type WHERE typnamespace = 'public'::regnamespace AND typtype = 'e') AS enums,
       (SELECT COUNT(*) FROM pg_proc WHERE pronamespace = 'public'::regnamespace) AS functions,
       (SELECT COUNT(*) FROM pg_sequences WHERE schemaname = 'public') AS sequences;

ROLLBACK;
