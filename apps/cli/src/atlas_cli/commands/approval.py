"""Implementation of 'atlas approval' subcommands: list, grant, and deny."""

import sys

from atlas_coordination.approval_manager import ApprovalManager, ApprovalStatus
from atlas_storage import SQLiteStorage

from atlas_cli.config import get_db_path


def _get_approval_manager() -> tuple[ApprovalManager, SQLiteStorage] | tuple[None, None]:
    """Initialize storage and ApprovalManager from local workspace."""
    db_path = get_db_path()
    if not db_path.exists():
        print("Error: ATLAS workspace is not initialized. Run 'atlas init' first.", file=sys.stderr)
        return None, None
    storage = SQLiteStorage(str(db_path))
    storage.initialize()
    manager = ApprovalManager()
    return manager, storage


def run_approval_list(status_filter: str | None = None) -> int:
    """List pending and resolved approval requests."""
    manager, storage = _get_approval_manager()
    if manager is None or storage is None:
        return 1

    try:
        status_enum = ApprovalStatus(status_filter.upper()) if status_filter else None
    except ValueError:
        print(
            f"Error: Invalid status '{status_filter}'. Valid choices: PENDING, GRANTED, DENIED, EXPIRED",
            file=sys.stderr,
        )
        return 1

    requests = manager.list_requests(status=status_enum)
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


def run_approval_grant(request_id: str, reason: str | None = None) -> int:
    """Grant authorization for a pending elevated action."""
    manager, storage = _get_approval_manager()
    if manager is None or storage is None:
        return 1

    try:
        granted = manager.grant(
            request_id=request_id,
            operator_id="cli_operator",
            reason=reason or "Approved via CLI",
        )
        print(
            f"[✔] Successfully granted approval '{granted.request_id}' for task '{granted.task_id}'."
        )
        return 0
    except KeyError:
        print(f"Error: Approval request '{request_id}' not found.", file=sys.stderr)
        return 1
    except ValueError as val_err:
        print(f"Error: {val_err}", file=sys.stderr)
        return 1


def run_approval_deny(request_id: str, reason: str | None = None) -> int:
    """Deny authorization for a pending elevated action."""
    manager, storage = _get_approval_manager()
    if manager is None or storage is None:
        return 1

    try:
        denied = manager.deny(
            request_id=request_id,
            operator_id="cli_operator",
            reason=reason or "Rejected via CLI",
        )
        print(
            f"[✘] Successfully denied approval '{denied.request_id}' for task '{denied.task_id}'."
        )
        return 0
    except KeyError:
        print(f"Error: Approval request '{request_id}' not found.", file=sys.stderr)
        return 1
    except ValueError as val_err:
        print(f"Error: {val_err}", file=sys.stderr)
        return 1
