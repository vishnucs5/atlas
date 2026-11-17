"""Session inspection, resumption, and export CLI commands."""

from pathlib import Path

from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    GREEN,
    RED,
    colorize,
    render_badge,
    render_table,
)
from atlas_cli.sessions.manager import SessionManager


def run_sessions_list(limit: int = 50) -> int:
    """List persistent CLI interactive sessions."""
    mgr = SessionManager()
    sessions = mgr.list_sessions(limit=limit)

    print(colorize("\n[ATLAS CLI SESSIONS]", BOLD + CYAN))
    if not sessions:
        print("No saved CLI sessions found.")
        return 0

    headers = ["Session ID", "Created At", "Status", "Objective Snippet"]
    rows = []
    for s in sessions:
        rows.append(
            [
                s.get("session_id"),
                s.get("created_at", "")[:19].replace("T", " "),
                render_badge(
                    s.get("status", "ACTIVE"),
                    "success" if s.get("status") == "COMPLETED" else "primary",
                ),
                (s.get("objective") or "")[:40],
            ]
        )
    print(render_table(headers, rows))
    return 0


def run_sessions_resume(session_id: str) -> int:
    """Resume an existing CLI session."""
    mgr = SessionManager()
    data = mgr.get_session(session_id)
    if not data:
        print(colorize(f"Error: Session '{session_id}' not found.", RED))
        return 1

    print(colorize(f"\n[RESUME SESSION: {session_id}]", BOLD + GREEN))
    print(f"Objective: {data.get('objective')}")
    print(f"Status:    {render_badge(data.get('status', 'ACTIVE'), 'primary')}")
    print("Re-attaching to execution context...")
    return 0


def run_sessions_export(session_id: str, output: str | None = None) -> int:
    """Export session artifacts to a file."""
    mgr = SessionManager()
    out_path = Path(output) if output else None
    try:
        exported = mgr.export_session(session_id, output_path=out_path)
        print(colorize(f"✓ Session exported successfully to: {exported}", BOLD + GREEN))
        return 0
    except Exception as exc:
        print(colorize(f"✗ Failed to export session: {exc}", RED))
        return 1
