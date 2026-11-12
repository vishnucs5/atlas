"""Implementation of 'atlas init' workspace initialization command."""

import json
import sys
from datetime import UTC, datetime

from atlas_storage import SQLiteStorage

from atlas_cli.config import get_atlas_dir, get_config_path, get_db_path


def run_init() -> int:
    """Initialize local .atlas/ workspace directory, configuration, and SQLite storage."""
    try:
        atlas_dir = get_atlas_dir()
        config_path = get_config_path()
        db_path = get_db_path()

        # Create workspace directory
        atlas_dir.mkdir(parents=True, exist_ok=True)

        # Write workspace configuration if not present
        if not config_path.exists():
            config_data = {
                "schema_version": "1.0",
                "created_at": datetime.now(UTC).isoformat(),
                "storage": {
                    "backend": "sqlite",
                    "database": db_path.name,
                },
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

        # Initialize SQLite database schema and WAL mode
        storage = SQLiteStorage(str(db_path))
        storage.initialize()
        storage.close()

        print(f"Initialized ATLAS workspace at {atlas_dir}")
        print(f"Database ready at {db_path}")
        return 0
    except Exception as exc:
        print(f"Error initializing ATLAS workspace: {exc}", file=sys.stderr)
        return 1
