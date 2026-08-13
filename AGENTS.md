# PostgreSQL schema changes

Whenever adding or modifying a Flyway migration in this repository:

- Update the sibling Fastify repository's `prisma/schema.prisma` so it remains
  synchronized with the PostgreSQL schema.
- Run `npm --prefix ../fastify run generate:entities`.
- Include and validate every resulting generated change under
  `../fastify/src/lib/entities` in the same work as the migration.
- Do not manually edit files under `../fastify/src/lib/entities`; that
  directory is owned by the Fastify repository's
  `scripts/generate-entities.ts`.

PostgreSQL schema changes include both Flyway migrations and direct changes to
the Fastify Prisma schema.
