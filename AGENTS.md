# PostgreSQL schema ownership

The sibling Fastify repository owns PostgreSQL schema changes. Add or modify
Flyway migrations under `../fastify/database/migrations`, keep
`../fastify/prisma/schema.prisma` synchronized, run
`npm --prefix ../fastify run generate:entities`, and include every resulting
generated change under `../fastify/src/lib/entities` in the same work.

Do not manually edit files under `../fastify/src/lib/entities`; that directory
is owned by the Fastify repository's `scripts/generate-entities.ts`.

This repository owns ingestion, model computation, and audited dataset
publication. Do not add a second migration set here.
