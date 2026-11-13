"""Unit tests verifying Milestone 4 deployment configuration, compose topology, and session validation."""

import sqlite3
import sys
from pathlib import Path

from atlas_browser.desktop import DesktopDriver
from atlas_storage.sqlite import SQLiteStorage


def test_windows_session_validation() -> None:
    """Verify DesktopDriver inspects and validates OS desktop session."""
    is_interactive, msg = DesktopDriver.validate_interactive_session()
    if sys.platform == "win32":
        # On developer machine, test runs inside an interactive Windows session (Session > 0)
        session_id = DesktopDriver.get_windows_session_id()
        assert session_id is not None
        assert isinstance(session_id, int)
        if session_id > 0:
            assert is_interactive is True
            assert f"Session ID: {session_id}" in msg
        else:
            assert is_interactive is False
            assert "Session 0" in msg
    else:
        assert is_interactive is True
        assert "Non-Windows" in msg


def test_compose_yaml_topology_and_env_example() -> None:
    """Verify compose.yaml contains api, worker, and postgres services and .env.example defines keys."""
    compose_path = Path("compose.yaml")
    assert compose_path.is_file()
    content = compose_path.read_text(encoding="utf-8")

    assert "atlas-postgres:" in content
    assert "atlas-api:" in content
    assert "atlas-worker:" in content
    assert "postgres:16-alpine" in content
    assert "atlas_postgres_data:" in content

    env_path = Path(".env.example")
    assert env_path.is_file()
    env_content = env_path.read_text(encoding="utf-8")

    assert "ATLAS_API_KEY_ADMIN" in env_content
    assert "ATLAS_DATABASE_URL" in env_content
    assert "ATLAS_BLOCK_PRIVATE_NETWORKS" in env_content
    assert "ATLAS_MAX_QUEUE_DEPTH" in env_content


def test_clean_startup_from_scratch(tmp_path: Path) -> None:
    """Verify clean database initialization from scratch without existing files."""
    db_file = tmp_path / "fresh_install" / "atlas_prod.db"
    assert not db_file.exists()

    storage = SQLiteStorage(str(db_file))
    storage.initialize()
    assert db_file.is_file()

    # Check that PRAGMA integrity check passes on fresh database
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "ok"

        # Verify all essential tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {r[0] for r in cursor.fetchall()}
        required = {
            "tasks",
            "execution_events",
            "checkpoints",
            "action_ledger",
            "worker_leases",
            "worker_registry",
        }
        assert required.issubset(tables)
    finally:
        conn.close()
        storage.close()
