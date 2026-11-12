"""Configuration and path resolution utilities for ATLAS CLI."""

import os
from pathlib import Path


def get_atlas_dir() -> Path:
    """Resolve the .atlas workspace directory based on ATLAS_HOME or current working directory."""
    if "ATLAS_HOME" in os.environ:
        home = Path(os.environ["ATLAS_HOME"]).resolve()
        if home.name == ".atlas":
            return home
        return home / ".atlas"
    return (Path.cwd() / ".atlas").resolve()


def get_db_path() -> Path:
    """Resolve the SQLite database file path."""
    if "ATLAS_HOME" in os.environ:
        home = Path(os.environ["ATLAS_HOME"]).resolve()
        if (home / "atlas.db").exists():
            return home / "atlas.db"
    return get_atlas_dir() / "atlas.db"


def get_config_path() -> Path:
    """Resolve the workspace config.json file path."""
    return get_atlas_dir() / "config.json"
