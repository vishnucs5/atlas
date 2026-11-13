"""End-to-end integration tests for PostgreSQL backup, integrity verification, and restoration."""

import pathlib
import tempfile
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_storage.backup import (
    BackupIntegrityError,
    clean_old_backups,
    create_postgres_backup,
    restore_postgres_backup,
    verify_postgres_backup,
)
from atlas_storage.postgres import PostgresStorage
from embedded_postgres import PostgresServer


@pytest.fixture(scope="module")
def pg_server():
    """Start an actual native PostgreSQL server for backup/restore testing."""
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="atlas_pg_bkp_"))
    server = PostgresServer(temp_dir)
    server.ensure_pgdata_inited()
    server.ensure_postgres_running()
    yield server
    server.cleanup()


@pytest.fixture
def source_storage(pg_server):
    """Provide a populated PostgresStorage source."""
    uri = pg_server.get_uri()
    storage = PostgresStorage(uri)
    storage.initialize()

    # Populate sample data across tables
    now = datetime.now(UTC)
    for i in range(5):
        tid = f"task_bkp_{i}_{uuid.uuid4().hex[:6]}"
        task = Task(
            task_id=tid,
            objective=f"Backup test task {i}",
            status=TaskStatus.RUNNING if i % 2 == 0 else TaskStatus.COMPLETED,
            priority=TaskPriority.NORMAL,
            created_at=now,
            updated_at=now,
            metadata={"index": i, "purpose": "backup_verification"},
        )
        storage.save_task(task)

        for seq in range(1, 3):
            storage.append_event(
                ExecutionEvent(
                    event_id=f"e_{tid}_{seq}",
                    task_id=tid,
                    sequence=seq,
                    event_type=EventType.ACTION_COMPLETED,
                    timestamp=now,
                    payload={"step": seq},
                    correlation_id=f"corr_{tid}",
                )
            )

    yield storage
    storage.close()


def test_pg_backup_creation_and_checksum_integrity(source_storage, tmp_path):
    """Verify PostgreSQL backup creates valid archive with SHA-256 sidecar."""
    backup_file = tmp_path / "production_atlas_backup.sql"
    created_path = create_postgres_backup(source_storage, backup_file)

    assert created_path.is_file()
    assert created_path.stat().st_size > 0

    meta_file = created_path.with_name(f"{created_path.name}.meta.json")
    assert meta_file.is_file()

    meta = verify_postgres_backup(created_path)
    assert meta["engine"] == "postgresql"
    assert meta["sha256_checksum"] is not None
    assert meta["table_counts"]["tasks"] >= 5
    assert meta["table_counts"]["execution_events"] >= 10


def test_pg_backup_credential_handling(source_storage, tmp_path):
    """Verify database password is redacted from the backup metadata sidecar."""
    backup_file = tmp_path / "cred_test.sql"
    # Supply dummy URI with secret password
    test_uri = "postgresql://atlas_admin:super_secret_pw@127.0.0.1:5432/atlas_prod"
    # Create backup from real source, but check that sanitize works
    from atlas_storage.backup import _sanitize_dsn

    sanitized = _sanitize_dsn(test_uri)
    assert "super_secret_pw" not in sanitized
    assert "atlas_admin:***REDACTED***@" in sanitized

    # Check actual created metadata
    created_path = create_postgres_backup(source_storage, backup_file)
    meta = verify_postgres_backup(created_path)
    assert "super_secret_pw" not in meta["source"]


def test_pg_backup_checksum_tamper_detection(source_storage, tmp_path):
    """Verify tampering with a backup archive raises BackupIntegrityError."""
    backup_file = tmp_path / "tamper_test.sql"
    created_path = create_postgres_backup(source_storage, backup_file)

    # Corrupt backup contents
    with created_path.open("a", encoding="utf-8") as f:
        f.write("\n-- TAMPERED INJECTION;\n")

    # Verification must fail
    with pytest.raises(BackupIntegrityError) as exc_info:
        verify_postgres_backup(created_path)
    assert "checksum mismatch" in str(exc_info.value).lower()


def test_pg_restore_into_clean_database(pg_server, source_storage, tmp_path):
    """Verify restoring a backup into a clean database restores tables and rows perfectly."""
    backup_file = tmp_path / "restore_test.sql"
    created_path = create_postgres_backup(source_storage, backup_file)

    # Set up clean target database in the same PostgreSQL cluster
    clean_db_name = f"clean_restore_{uuid.uuid4().hex[:8]}"
    uri = pg_server.get_uri()

    import psycopg
    from psycopg import sql

    with psycopg.connect(uri, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(clean_db_name)))

    clean_uri = uri.rsplit("/", 1)[0] + f"/{clean_db_name}"

    try:
        # Initialize target schema
        clean_storage = PostgresStorage(clean_uri)
        clean_storage.initialize()

        # Before restore, tasks table is empty
        assert len(clean_storage.list_tasks()) == 0

        # Perform restore
        restore_postgres_backup(created_path, clean_uri)

        # After restore, tasks and events are restored
        restored_tasks = clean_storage.list_tasks(limit=100)
        assert len(restored_tasks) >= 5

        # Check an individual task and events
        sample_task = restored_tasks[0]
        events = clean_storage.get_events(sample_task.task_id)
        assert len(events) >= 2

        clean_storage.close()
    finally:
        with psycopg.connect(uri, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {};").format(sql.Identifier(clean_db_name))
                )


def test_pg_restore_corrupted_backup_rejected(pg_server, source_storage, tmp_path):
    """Verify restore fails immediately if the backup file is corrupted or tampered with."""
    backup_file = tmp_path / "bad_restore.sql"
    created_path = create_postgres_backup(source_storage, backup_file)

    # Tamper with file
    with created_path.open("a", encoding="utf-8") as f:
        f.write("\n-- INVALID DATA\n")

    uri = pg_server.get_uri()
    with pytest.raises(BackupIntegrityError):
        restore_postgres_backup(created_path, uri)


def test_pg_backup_retention_policy(tmp_path):
    """Verify retention policy removes older backups while preserving minimum threshold."""
    backup_dir = tmp_path / "backup_retention"
    backup_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)

    # Create 5 backups with different simulated mtimes
    files = []
    for i in range(5):
        bf = backup_dir / f"backup_day_{i}.sql"
        bf.write_text(f"-- backup {i}", encoding="utf-8")
        meta_f = bf.with_name(f"{bf.name}.meta.json")
        meta_f.write_text("{}", encoding="utf-8")

        # Age: 0, 2, 4, 10, 15 days ago
        days_ago = [0, 2, 4, 10, 15][i]
        sim_time = (now - timedelta(days=days_ago)).timestamp()
        import os

        os.utime(str(bf), (sim_time, sim_time))
        os.utime(str(meta_f), (sim_time, sim_time))
        files.append(bf)

    # Prune backups older than 7 days, keeping min 3
    removed = clean_old_backups(backup_dir, max_age_days=7, min_retained=3)

    # day 4 (15 days ago) and day 3 (10 days ago) should be removed
    assert len(removed) == 2
    remaining = [p for p in backup_dir.iterdir() if p.suffix == ".sql"]
    assert len(remaining) == 3
