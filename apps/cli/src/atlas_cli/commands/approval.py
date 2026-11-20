"""Durable CLI approval commands for local ATLAS orchestration tasks."""

from __future__ import annotations

import asyncio
import sys

from atlas_coordination.approval_manager import (
    ApprovalManager,
    ApprovalSecurityError,
    ApprovalStatus,
)
from atlas_storage import SQLiteStorage

from atlas_cli.config import get_db_path


def _get_approval_manager() -> tuple[ApprovalManager, SQLiteStorage] | tuple[None, None]:
    """Load signed pending approvals from persisted task metadata."""
    db_path = get_db_path()
    if not db_path.exists():
        print("Error: ATLAS workspace is not initialized. Run 'atlas init' first.", file=sys.stderr)
        return None, None
    storage = SQLiteStorage(str(db_path))
    storage.initialize()
    manager = ApprovalManager()
    try:
        for task in storage.list_tasks(limit=1000):
            persisted = task.metadata.get("pending_approval")
            if persisted:
                manager.restore_request(persisted)
    except (ApprovalSecurityError, ValueError, TypeError) as exc:
        storage.close()
        print(f"Error loading persisted approvals: {type(exc).__name__}", file=sys.stderr)
        return None, None
    return manager, storage


def run_approval_list(status_filter: str | None = None) -> int:
    """List durable pending and resolved approval requests."""
    manager, storage = _get_approval_manager()
    if manager is None or storage is None:
        return 1
    try:
        status_enum = ApprovalStatus(status_filter.upper()) if status_filter else None
        requests = manager.list_requests(status=status_enum)
    except ValueError:
        print(
            "Error: Invalid status. Valid choices: PENDING, GRANTED, DENIED, EXPIRED",
            file=sys.stderr,
        )
        return 1
    finally:
        storage.close()

    if not requests:
        status_str = f" with status '{status_filter}'" if status_filter else ""
        print(f"No approval requests found{status_str}.")
        return 0
    print(
        f"{'REQUEST ID':<18} {'TASK ID':<18} {'STATUS':<10} {'RISK':<8} {'ACTION':<20} {'REASON'}"
    )
    print("-" * 90)
    for req in requests:
        print(
            f"{req.request_id:<18} {req.task_id:<18} {req.status.value:<10} "
            f"{req.risk_level:<8} {req.action_type:<20} {req.reason[:30]}"
        )
    return 0


def _resolve_approval(request_id: str, *, grant: bool, reason: str | None) -> int:
    manager, storage = _get_approval_manager()
    if manager is None or storage is None:
        return 1
    if manager.get_request(request_id) is None:
        storage.close()
        print(f"Error: Approval request '{request_id}' not found.", file=sys.stderr)
        return 1

    from atlas_agent.runtime import ProductionRuntime

    runtime = ProductionRuntime(storage=storage, approval_manager=manager)
    try:
        if grant:
            task = asyncio.run(
                runtime.grant_approval(
                    request_id,
                    operator_id="cli_operator",
                    reason=reason or "Approved via CLI",
                )
            )
            print(f"GRANTED: {request_id} resumed task {task.task_id} ({task.status.value}).")
        else:
            task = asyncio.run(
                runtime.deny_approval(
                    request_id,
                    operator_id="cli_operator",
                    reason=reason or "Rejected via CLI",
                )
            )
            print(f"DENIED: {request_id} closed task {task.task_id} ({task.status.value}).")
        return 0
    except (KeyError, ValueError, ApprovalSecurityError) as exc:
        print(f"Error resolving approval: {exc}", file=sys.stderr)
        return 1
    finally:
        asyncio.run(runtime.shutdown())


def run_approval_grant(request_id: str, reason: str | None = None) -> int:
    """Grant a signed approval and resume the exact persisted action."""
    return _resolve_approval(request_id, grant=True, reason=reason)


def run_approval_deny(request_id: str, reason: str | None = None) -> int:
    """Deny a signed approval and transition the associated task to FAILED."""
    return _resolve_approval(request_id, grant=False, reason=reason)
