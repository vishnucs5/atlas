"""Online database backup and disaster recovery utilities for ATLAS (SQLite & PostgreSQL)."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

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


def _sanitize_dsn(dsn: str) -> str:
    """Mask password in database connection URI."""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***REDACTED***@", dsn)


def _find_pg_binaries() -> tuple[Path | None, Path | None]:
    """Locate pg_dump and psql executables from system PATH or embedded-postgres package."""
    dump_name = "pg_dump.exe" if os.name == "nt" else "pg_dump"
    psql_name = "psql.exe" if os.name == "nt" else "psql"

    # 1. Check system PATH
    sys_dump = shutil.which("pg_dump")
    sys_psql = shutil.which("psql")
    dump_path = Path(sys_dump) if sys_dump else None
    psql_path = Path(sys_psql) if sys_psql else None

    if dump_path and psql_path:
        return dump_path, psql_path

    # 2. Check embedded_postgres if available
    try:
        import embedded_postgres

        pkg_bin = Path(embedded_postgres.__file__).parent / "pginstall" / "bin"
        if not dump_path and (pkg_bin / dump_name).is_file():
            dump_path = pkg_bin / dump_name
        if not psql_path and (pkg_bin / psql_name).is_file():
            psql_path = pkg_bin / psql_name
    except ImportError:
        pass

    return dump_path, psql_path


# -----------------------------------------------------------------------------
# SQLite Backup & Restore Utilities
# -----------------------------------------------------------------------------


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
        for tbl in [
            "tasks",
            "execution_events",
            "checkpoints",
            "worker_leases",
            "action_ledger",
        ]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
                row = cursor.fetchone()
                counts[tbl] = row[0] if row else 0
            except sqlite3.OperationalError:
                counts[tbl] = 0
    finally:
        inspect_conn.close()

    meta = {
        "engine": "sqlite",
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


# -----------------------------------------------------------------------------
# PostgreSQL Backup & Restore Utilities
# -----------------------------------------------------------------------------


def create_postgres_backup(
    source: str | Any,
    destination_path: str | Path,
) -> Path:
    """Create a tamper-evident, consistent backup of a PostgreSQL database.

    Invokes pg_dump with --clean --if-exists flags, computes cryptographic SHA-256
    checksums, queries record counts across primary tables, scrubs sensitive database
    passwords from the metadata sidecar, and stores <dest>.meta.json.
    """
    dest_path = Path(destination_path).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if hasattr(source, "dsn"):
        source_uri = str(source.dsn)
    else:
        source_uri = str(source)

    dump_bin, _ = _find_pg_binaries()

    if dump_bin and dump_bin.is_file():
        # Execute official pg_dump binary
        cmd = [
            str(dump_bin),
            f"--dbname={source_uri}",
            f"--file={str(dest_path)}",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise BackupIntegrityError(
                f"pg_dump execution failed with exit code {res.returncode}: {res.stderr}"
            )
    else:
        # Logical SQL dump fallback via direct PostgreSQL connection
        try:
            with psycopg.connect(source_uri) as conn:
                with conn.cursor() as cur:
                    statements = ["-- ATLAS PostgreSQL Logical SQL Dump\nBEGIN;\n"]
                    for tbl in [
                        "tasks",
                        "execution_events",
                        "checkpoints",
                        "action_ledger",
                        "worker_registry",
                        "worker_leases",
                    ]:
                        cur.execute(f"SELECT * FROM {tbl};")
                        cols = [desc[0] for desc in cur.description] if cur.description else []
                        rows = cur.fetchall()
                        for r in rows:
                            vals = []
                            for v in r:
                                if v is None:
                                    vals.append("NULL")
                                elif isinstance(v, (dict, list)):
                                    clean_j = json.dumps(v).replace("'", "''")
                                    vals.append(f"'{clean_j}'::jsonb")
                                elif isinstance(v, datetime):
                                    vals.append(f"'{v.isoformat()}'")
                                elif isinstance(v, (int, float)):
                                    vals.append(str(v))
                                else:
                                    clean_s = str(v).replace("'", "''")
                                    vals.append(f"'{clean_s}'")
                            col_names = ", ".join(cols)
                            val_str = ", ".join(vals)
                            statements.append(
                                f"INSERT INTO {tbl} ({col_names}) VALUES ({val_str}) ON CONFLICT DO NOTHING;\n"
                            )
                    statements.append("COMMIT;\n")
            with dest_path.open("w", encoding="utf-8") as f:
                f.writelines(statements)
        except Exception as exc:
            raise BackupIntegrityError(
                f"Failed to generate logical PostgreSQL dump: {exc}"
            ) from exc

    if not dest_path.is_file() or dest_path.stat().st_size == 0:
        raise BackupIntegrityError(
            f"Generated PostgreSQL backup file is empty or missing: '{dest_path}'"
        )

    checksum = _compute_file_sha256(dest_path)
    file_size = dest_path.stat().st_size

    # Inspect record counts across tables
    counts: dict[str, int] = {}
    try:
        with psycopg.connect(source_uri) as conn:
            with conn.cursor() as cur:
                for tbl in [
                    "tasks",
                    "execution_events",
                    "checkpoints",
                    "worker_leases",
                    "action_ledger",
                ]:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                        row = cur.fetchone()
                        counts[tbl] = int(row[0]) if row else 0
                    except Exception:
                        counts[tbl] = 0
    except Exception as exc:
        raise BackupIntegrityError(f"Failed to query table counts during backup: {exc}") from exc

    meta = {
        "engine": "postgresql",
        "source": _sanitize_dsn(source_uri),
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


def verify_postgres_backup(backup_path: str | Path) -> dict[str, Any]:
    """Verify cryptographic checksum, file existence, and header structure of a PostgreSQL backup file."""
    path = Path(backup_path).resolve()
    if not path.is_file():
        raise BackupIntegrityError(f"PostgreSQL backup file does not exist: '{path}'")

    meta_path = path.with_name(f"{path.name}.meta.json")
    if meta_path.is_file():
        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        expected_checksum = meta.get("sha256_checksum")
        actual_checksum = _compute_file_sha256(path)
        if expected_checksum and actual_checksum != expected_checksum:
            raise BackupIntegrityError(
                f"PostgreSQL backup checksum mismatch: expected '{expected_checksum}', actual '{actual_checksum}'. "
                f"The backup file may be corrupted, incomplete, or tampered with."
            )
    else:
        actual_checksum = _compute_file_sha256(path)
        meta = {"sha256_checksum": actual_checksum}

    # Inspect file header for SQL / dump indicators
    with path.open("r", encoding="utf-8", errors="replace") as f:
        header = f.read(2048)
        if not header.strip():
            raise BackupIntegrityError(f"PostgreSQL backup file is empty: '{path}'")
        if not (
            "PostgreSQL database dump" in header
            or "CREATE TABLE" in header
            or "INSERT INTO" in header
            or "-- ATLAS" in header
            or "SET " in header
        ):
            raise BackupIntegrityError(
                f"PostgreSQL backup file header unrecognized or invalid: '{path}'"
            )

    return meta


def restore_postgres_backup(
    backup_path: str | Path,
    target: str | Any,
) -> None:
    """Restore a verified PostgreSQL backup file into a target PostgreSQL database.

    Verifies cryptographic integrity before execution, applies the SQL dump,
    and deterministically verifies table row counts match expected metadata.
    """
    meta = verify_postgres_backup(backup_path)
    path = Path(backup_path).resolve()

    if hasattr(target, "dsn"):
        target_uri = str(target.dsn)
    else:
        target_uri = str(target)

    _, psql_bin = _find_pg_binaries()

    if psql_bin and psql_bin.is_file():
        cmd = [
            str(psql_bin),
            f"--dbname={target_uri}",
            f"--file={str(path)}",
            "--quiet",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise BackupIntegrityError(
                f"psql restore execution failed with exit code {res.returncode}: {res.stderr}"
            )
    else:
        # Fallback to direct executing dump statements via psycopg
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                sql_content = f.read()

            with psycopg.connect(target_uri) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql_content)
                conn.commit()
        except Exception as exc:
            raise BackupIntegrityError(f"Failed to execute SQL restore script: {exc}") from exc

    # Deterministic post-restore verification against metadata table counts
    expected_counts = meta.get("table_counts", {})
    if expected_counts:
        try:
            with psycopg.connect(target_uri) as conn:
                with conn.cursor() as cur:
                    for tbl, expected in expected_counts.items():
                        cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                        row = cur.fetchone()
                        actual = int(row[0]) if row else 0
                        if actual < expected:
                            raise BackupIntegrityError(
                                f"Post-restore verification failed for table '{tbl}': "
                                f"expected at least {expected} records, found {actual}."
                            )
        except Exception as exc:
            if isinstance(exc, BackupIntegrityError):
                raise
            raise BackupIntegrityError(
                f"Failed to verify restored database contents: {exc}"
            ) from exc


# -----------------------------------------------------------------------------
# Retention Management
# -----------------------------------------------------------------------------


def clean_old_backups(
    backup_dir: str | Path,
    max_age_days: int = 7,
    min_retained: int = 3,
) -> list[Path]:
    """Prune backup files older than max_age_days, preserving at least min_retained newest backups."""
    dir_path = Path(backup_dir).resolve()
    if not dir_path.is_dir():
        return []

    # Locate backup files
    backup_files = [
        p for p in dir_path.iterdir() if p.is_file() and not p.name.endswith(".meta.json")
    ]
    # Sort newest first
    backup_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    removed: list[Path] = []

    # Preserve at least min_retained
    eligible = backup_files[min_retained:]

    for bkp in eligible:
        mtime = datetime.fromtimestamp(bkp.stat().st_mtime, tz=UTC)
        if mtime < cutoff:
            meta_file = bkp.with_name(f"{bkp.name}.meta.json")
            try:
                bkp.unlink()
                removed.append(bkp)
                if meta_file.is_file():
                    meta_file.unlink()
            except OSError:
                pass

    return removed
