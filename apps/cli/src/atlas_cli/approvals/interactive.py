"""Interactive and batch approval operations for Action Firewall governance."""

import sys

from atlas_cli.adapters.client import AtlasClient
from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    YELLOW,
    colorize,
    render_badge,
    render_table,
)


def run_interactive_approvals(client: AtlasClient | None = None) -> int:
    """Prompt the operator interactively for all pending Action Firewall approvals."""
    client = client or AtlasClient()
    approvals = client.list_approvals(status="PENDING")

    if not approvals:
        print(colorize("\n✓ No pending Action Firewall approvals. Cluster is safe.", GREEN))
        return 0

    print(
        colorize(
            f"\n[!] {len(approvals)} Action Firewall approval(s) requiring human authorization:\n",
            BOLD + YELLOW,
        )
    )

    for idx, req in enumerate(approvals, 1):
        req_id = req.get("request_id")
        action_type = req.get("action_type")
        risk_level = req.get("risk_level", "HIGH")
        reason = req.get("reason", "Action requires human oversight")
        task_id = req.get("task_id", "Unknown")

        print("=" * 60)
        print(f"Request #{idx}/{len(approvals)}: {colorize(req_id, BOLD + CYAN)}")
        print(f"Task ID:     {task_id}")
        print(f"Action:      {colorize(action_type, BOLD)}")
        print(
            f"Risk Level:  {render_badge(risk_level, 'warning' if risk_level != 'CRITICAL' else 'danger')}"
        )
        print(f"Policy Note: {reason}")
        print("-" * 60)

        if not sys.stdin.isatty():
            # Non-interactive fallback
            print(f"Non-interactive terminal: Approval {req_id} left PENDING.")
            continue

        try:
            choice = (
                input(
                    f"Authorize action? [{colorize('Y', GREEN)}es / {colorize('N', RED)}o / {colorize('S', YELLOW)}kip]: "
                )
                .strip()
                .lower()
            )
            if choice in ("y", "yes"):
                justification = (
                    input("Authorization justification [optional]: ").strip()
                    or "Approved interactively via CLI"
                )
                res = client.grant_approval(req_id, reason=justification)
                if "error" not in res:
                    print(colorize(f"✓ Request {req_id} GRANTED.", GREEN))
                else:
                    print(colorize(f"✗ Failed to grant: {res.get('error')}", RED))
            elif choice in ("n", "no"):
                denial_reason = (
                    input("Denial reason [optional]: ").strip() or "Denied interactively via CLI"
                )
                res = client.deny_approval(req_id, reason=denial_reason)
                if "error" not in res:
                    print(colorize(f"✗ Request {req_id} DENIED.", RED))
                else:
                    print(colorize(f"✗ Failed to deny: {res.get('error')}", RED))
            else:
                print(colorize(f"Skipped {req_id}.", DIM))
        except (KeyboardInterrupt, EOFError):
            print("\nExiting approval review.")
            return 130

    return 0


def render_approvals_list(
    client: AtlasClient | None = None, status_filter: str | None = None
) -> int:
    """Print a clean table of approvals."""
    client = client or AtlasClient()
    approvals = client.list_approvals(status=status_filter)

    if not approvals:
        print("No approval requests found.")
        return 0

    headers = ["Request ID", "Task ID", "Action Type", "Risk", "Status", "Reason"]
    rows = []
    for a in approvals:
        rows.append(
            [
                a.get("request_id"),
                a.get("task_id"),
                a.get("action_type"),
                a.get("risk_level"),
                render_badge(
                    a.get("status", "PENDING"),
                    "warning" if a.get("status") == "PENDING" else "success",
                ),
                (a.get("reason") or "")[:40],
            ]
        )

    print(render_table(headers, rows))
    return 0
