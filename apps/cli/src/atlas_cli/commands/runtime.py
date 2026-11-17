"""Runtime operations, worker daemon management, and audit logs."""

from atlas_cli.adapters.client import AtlasClient
from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    DIM,
    colorize,
    render_badge,
    render_table,
)


def run_server_status(client: AtlasClient | None = None) -> int:
    """Check and display local API server health and uptime."""
    client = client or AtlasClient()
    health = client.get_server_health()
    online = health.get("status") in ("ok", "healthy")

    print(colorize("\n[ATLAS API SERVER RUNTIME]", BOLD + CYAN))
    print(f"Endpoint:   {client.base_url}")
    print(
        f"Status:     {render_badge('ONLINE', 'success') if online else render_badge('OFFLINE', 'danger')}"
    )
    if online:
        print(f"Version:    {health.get('version', '0.1.0')}")
        print(f"Storage:    {health.get('storage', 'sqlite-wal')}")
        print("Runtime:    ProductionRuntime active")
    else:
        print(
            colorize(
                "Start the server using: uv run --package atlas-api uvicorn atlas_api.main:app --port 8000",
                DIM,
            )
        )
    return 0 if online else 1


def run_workers_list(client: AtlasClient | None = None) -> int:
    """List registered and leased worker daemons."""
    client = client or AtlasClient()
    workers = client.list_workers()

    print(colorize("\n[DISTRIBUTED FLEET WORKERS]", BOLD + CYAN))
    if not workers:
        print("No remote worker nodes currently connected. Running embedded local worker.")
        return 0

    headers = ["Worker ID", "Node Name", "Capabilities", "Status", "Heartbeat"]
    rows = []
    for w in workers:
        st = w.get("status", "ACTIVE")
        badge_type = "success" if st in ("ACTIVE", "HEALTHY") else "warning"
        rows.append(
            [
                w.get("worker_id"),
                w.get("name", "local-node"),
                ", ".join(w.get("capabilities", [])),
                render_badge(st, badge_type),
                w.get("last_heartbeat", "recent"),
            ]
        )
    print(render_table(headers, rows))
    return 0


def run_logs(limit: int = 30, client: AtlasClient | None = None) -> int:
    """Fetch and stream recent execution and security audit events."""
    client = client or AtlasClient()
    print(colorize(f"\n[ATLAS AUDIT LOG STREAM (Last {limit} events)]", BOLD + CYAN))

    # Fetch tasks to display chronological execution log
    tasks = client.list_tasks(limit=limit)
    if not tasks:
        print("Zero log events recorded.")
        return 0

    headers = ["Timestamp", "Task ID", "Status", "Objective Snippet"]
    rows = []
    for t in tasks:
        rows.append(
            [
                t.get("updated_at", "")[:19].replace("T", " "),
                t.get("task_id"),
                render_badge(
                    t.get("status", "COMPLETED"),
                    "success" if t.get("status") == "COMPLETED" else "primary",
                ),
                (t.get("objective") or "")[:45],
            ]
        )
    print(render_table(headers, rows))
    return 0
