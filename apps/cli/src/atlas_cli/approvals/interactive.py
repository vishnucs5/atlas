"""Interactive and batch approval operations for Action Firewall governance."""

import json
import sys
from typing import Any

from atlas_cli.adapters.client import AtlasClient
from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    RESET,
    YELLOW,
    colorize,
    render_badge,
    render_table,
)


def format_approval_card(req: dict[str, Any]) -> str:
    """Format an explicit, high-integrity Action Firewall approval card."""
    req_id = req.get("request_id", "req_unknown")
    action_type = req.get("action_type", "unknown.action")
    target = req.get("target") or req.get("identifier") or "workspace"
    risk_level = req.get("risk_level", "HIGH")
    reason = req.get("reason", "Operation exceeds safe autonomous boundary.")
    scope = req.get("scope", "workspace")
    duration = req.get("timeout_seconds") or req.get("duration") or "60s"
    policy_version = req.get("policy_version", "1.0")
    parameters = req.get("parameters", {})

    risk_badge = render_badge(
        risk_level,
        "danger"
        if risk_level == "CRITICAL"
        else ("warning" if risk_level == "HIGH" else "success"),
    )

    lines = [
        colorize("┌─[ ACTION FIREWALL AUTHORIZATION REQUEST ]" + "─" * 38, BOLD + YELLOW),
        f"│ Request ID:      {colorize(req_id, BOLD + CYAN)}",
        f"│ Operation:       {colorize(action_type, BOLD)}",
        f"│ Target:          {colorize(str(target), CYAN)}",
        f"│ Risk Level:      {risk_badge}",
        f"│ Scope:           {colorize(str(scope), BOLD)}",
        f"│ Duration Cap:    {duration}",
        f"│ Policy Version:  {policy_version}",
        f"│ Policy Context:  {colorize(reason, DIM)}",
        "├─[ EXACT PARAMETERS ]" + "─" * 58,
    ]

    if parameters:
        params_json = json.dumps(parameters, indent=2)
        for p_line in params_json.splitlines():
            lines.append(f"│   {colorize(p_line, DIM)}")
    else:
        lines.append(f"│   {colorize('(no parameters)', DIM)}")

    lines.append("└" + "─" * 78)
    return "\n".join(lines)


def run_interactive_approvals(client: AtlasClient | None = None) -> int:
    """Prompt the operator interactively for all pending Action Firewall approvals."""
    client = client or AtlasClient()
    approvals = client.list_approvals(status="PENDING")

    if not approvals:
        print(colorize("\n✓ No pending Action Firewall approvals. Workspace is safe.", GREEN))
        return 0

    print(
        colorize(
            f"\n[!] {len(approvals)} Action Firewall approval(s) requiring explicit human authorization:\n",
            BOLD + YELLOW,
        )
    )

    for idx, req in enumerate(approvals, 1):
        req_id = str(req.get("request_id", ""))
        if not req_id:
            continue
        print(f"\nApproval Request #{idx} of {len(approvals)}:")
        print(format_approval_card(req))

        if not sys.stdin.isatty():
            # Non-interactive fallback
            print(f"Non-interactive terminal: Approval {req_id} preserved as PENDING.")
            continue

        try:
            choice = (
                input(
                    f"Authorize exact action? [{colorize('Y', GREEN)}es / {colorize('N', RED)}o / {colorize('S', YELLOW)}kip]: "
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
                    print(colorize(f"✓ Request {req_id} GRANTED by operator.", GREEN))
                else:
                    print(colorize(f"✗ Failed to grant approval: {res.get('error')}", RED))
            elif choice in ("n", "no"):
                denial_reason = (
                    input("Denial reason [optional]: ").strip() or "Denied interactively via CLI"
                )
                res = client.deny_approval(req_id, reason=denial_reason)
                if "error" not in res:
                    print(colorize(f"✗ Request {req_id} DENIED by operator.", RED))
                else:
                    print(colorize(f"✗ Failed to deny approval: {res.get('error')}", RED))
            else:
                print(colorize(f"Skipped {req_id}. Remains PENDING.", DIM))
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
        print(colorize("\nNo approvals found matching filter.", DIM))
        return 0

    headers = ["Request ID", "Operation", "Target", "Risk", "Status", "Created"]
    rows = []
    for a in approvals:
        st = a.get("status", "PENDING")
        badge = (
            render_badge("PENDING", "warning")
            if st == "PENDING"
            else (
                render_badge("GRANTED", "success")
                if st == "GRANTED"
                else render_badge("DENIED", "danger")
            )
        )
        rows.append(
            [
                a.get("request_id"),
                a.get("action_type"),
                str(a.get("target") or a.get("identifier") or ""),
                a.get("risk_level", "HIGH"),
                badge,
                a.get("created_at", "")[:19],
            ]
        )

    print(f"\n{BOLD}Action Firewall Approvals{RESET}")
    print(render_table(headers, rows))
    return 0
