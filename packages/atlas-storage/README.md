# ATLAS Storage Engine (`atlas-storage`)

Event-sourced task persistence and query engine for ATLAS (Autonomous Task & Lifecycle Automation System).

## Architecture

- **Local Development**: Embedded SQLite with Write-Ahead Logging (`WAL` mode), zero external dependencies, strict sequence validation, and transactional read projections.
- **Production Specification**: PostgreSQL storage specification, connection pooling configuration, and relational schema definitions in `atlas_storage.postgres`.
