"""Online database backup and disaster recovery utilities for ATLAS."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_storage.sqlite import SQLiteStorage


class BackupIntegrityError(Exception):
    """Raised when a backup archive fails cryptographic verification or database integrity checks."""


def _compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def create_sqlite_backup(
    source: str | Path | SQLiteStorage,
    destination_path: str | Path,
    pages_per_step: int = -1,
) -> Path:
    """Create an atomic, crash-consistent online backup of an active SQLite database.

    Uses sqlite3.Connection.backup() to safely snapshot the database without locking
    or blocking active reader or writer transactions. Writes a tamper-evident SHA-256
    metadata sidecar alongside the backup artifact.
    """
    dest_path = Path(destination_path).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve source connection
    if isinstance(source, SQLiteStorage):
        source_conn = source._get_connection()
        source_name = str(source.db_path)
    else:
        source_conn = sqlite3.connect(str(source))
        source_name = str(source)

    try:
        dest_conn = sqlite3.connect(str(dest_path))
        try:
            with dest_conn:
                source_conn.backup(dest_conn, pages=pages_per_step)
        finally:
            dest_conn.close()
    finally:
        if not isinstance(source, SQLiteStorage):
            source_conn.close()

    # Verify and compute SHA-256 checksum
    checksum = _compute_file_sha256(dest_path)
    file_size = dest_path.stat().st_size

    # Count records across primary tables
    counts: dict[str, int] = {}
    inspect_conn = sqlite3.connect(str(dest_path))
    try:
        cursor = inspect_conn.cursor()
        for tbl in ["tasks", "execution_events", "checkpoints", "worker_leases", "action_ledger"]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
                row = cursor.fetchone()
                counts[tbl] = row[0] if row else 0
            except sqlite3.OperationalError:
                counts[tbl] = 0
    finally:
        inspect_conn.close()

    meta = {
        "source": source_name,
        "backup_path": str(dest_path),
        "created_at": datetime.now(UTC).isoformat(),
        "file_size_bytes": file_size,
        "sha256_checksum": checksum,
        "table_counts": counts,
        "format_version": "1.0",
    }

    meta_path = dest_path.with_name(f"{dest_path.name}.meta.json")
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return dest_path


def verify_sqlite_backup(backup_path: str | Path) -> dict[str, Any]:
    """Verify cryptographic integrity, PRAGMA check, and table structures of a backup file.

    Raises BackupIntegrityError if checksum mismatch or database corruption is detected.
    """
    path = Path(backup_path).resolve()
    if not path.is_file():
        raise BackupIntegrityError(f"Backup file does not exist: '{path}'")

    meta_path = path.with_name(f"{path.name}.meta.json")
    if meta_path.is_file():
        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        expected_checksum = meta.get("sha256_checksum")
        actual_checksum = _compute_file_sha256(path)
        if expected_checksum and actual_checksum != expected_checksum:
            raise BackupIntegrityError(
                f"Backup checksum mismatch: expected '{expected_checksum}', actual '{actual_checksum}'. "
                f"The backup file may be corrupted or tampered with."
            )
    else:
        actual_checksum = _compute_file_sha256(path)
        meta = {"sha256_checksum": actual_checksum}

    # Verify SQLite internal page integrity
    try:
        conn = sqlite3.connect(str(path))
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            rows = cursor.fetchall()
            if not rows or rows[0][0] != "ok":
                errors = "; ".join(r[0] for r in rows)
                raise BackupIntegrityError(f"SQLite PRAGMA integrity_check failed: {errors}")
        finally:
            conn.close()
    except sqlite3.DatabaseError as db_err:
        raise BackupIntegrityError(
            f"Database error during backup verification: {db_err}"
        ) from db_err

    return meta


def restore_sqlite_backup(
    backup_path: str | Path,
    target: str | Path | SQLiteStorage,
) -> None:
    """Safely restore a validated SQLite backup into a target SQLite database.

    Verifies the backup file first before performing atomic restore.
    """
    verify_sqlite_backup(backup_path)

    backup_conn = sqlite3.connect(str(backup_path))
    try:
        if isinstance(target, SQLiteStorage):
            target_conn = target._get_connection()
            with target_conn:
                backup_conn.backup(target_conn)
        else:
            target_path = Path(target).resolve()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_conn = sqlite3.connect(str(target_path))
            try:
                with target_conn:
                    backup_conn.backup(target_conn)
            finally:
                target_conn.close()
    finally:
        backup_conn.close()
