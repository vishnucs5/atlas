# ATLAS Developer CLI (`apps/cli`)

Developer command-line interface for ATLAS (Autonomous Task & Lifecycle Automation System).

## Commands

- `atlas doctor`: Verify execution environment, Python version, platform, and SQLite WAL support.
- `atlas init`: Initialize `.atlas/` local workspace configuration and SQLite database.
- `atlas task create "<objective>"`: Create and persist a new task with initial `TASK_CREATED` event.
- `atlas task list`: List tasks with status and priority formatting.
- `atlas task inspect <task_id>`: View detailed task record and full execution event history with secret masking.
