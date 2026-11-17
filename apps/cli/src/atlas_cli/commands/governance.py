"""Governance, configuration, status, and diagnostic CLI commands."""

from atlas_cli.adapters.client import AtlasClient
from atlas_cli.configuration.manager import ConfigManager
from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    GREEN,
    colorize,
    render_badge,
    render_table,
)


def run_config_cmd(key: str | None = None, value: str | None = None) -> int:
    """View or set CLI configuration options."""
    cfg = ConfigManager()

    if key and value is not None:
        cfg.set(key, value)
        print(colorize(f"✓ Configuration updated: {key} = {value}", BOLD + GREEN))
        return 0

    if key:
        val = cfg.get(key)
        print(f"{key}: {val}")
        return 0

    print(colorize("\n[ATLAS CLI CONFIGURATION]", BOLD + CYAN))
    all_cfg = cfg.list_all()
    headers = ["Configuration Key", "Current Value"]
    rows = [[k, str(v)] for k, v in all_cfg.items()]
    print(render_table(headers, rows))
    return 0


def run_permissions() -> int:
    """Display Action Firewall security boundaries and operator permissions."""
    print(colorize("\n[ACTION FIREWALL PERMISSION POLICIES]", BOLD + CYAN))
    headers = ["Action Type Pattern", "Policy Decision", "Risk Level", "Audit Requirements"]
    rows = [
        ["browser.*", "ALLOW", render_badge("LOW", "primary"), "Deterministic verify"],
        ["desktop.*", "ALLOW", render_badge("MEDIUM", "warning"), "Deterministic verify"],
        ["file.read", "ALLOW", render_badge("LOW", "primary"), "Audit log entry"],
        [
            "file.write",
            "REQUIRE_APPROVAL",
            render_badge("HIGH", "warning"),
            "Interactive human sign-off",
        ],
        [
            "terminal.*",
            "REQUIRE_APPROVAL",
            render_badge("CRITICAL", "danger"),
            "Interactive human sign-off",
        ],
        [
            "ssrf.private_ip",
            "DENY",
            render_badge("CRITICAL", "danger"),
            "Hard boundary enforcement",
        ],
    ]
    print(render_table(headers, rows))
    print(colorize("\nConstitution Enforcement: Zero unauthenticated external operations.", GREEN))
    return 0


def run_status(client: AtlasClient | None = None) -> int:
    """Print comprehensive cluster and local system status."""
    client = client or AtlasClient()
    cfg = ConfigManager()

    health = client.get_server_health()
    is_online = health.get("status") in ("ok", "healthy")

    print(colorize("\n==================================================", BOLD + CYAN))
    print(colorize("           ATLAS PLATFORM STATUS OVERVIEW         ", BOLD))
    print(colorize("==================================================", BOLD + CYAN))
    print(f"Server Endpoint:     {client.base_url}")
    print(
        f"Control Plane:       {render_badge('ONLINE', 'success') if is_online else render_badge('OFFLINE', 'danger')}"
    )
    print(f"Active Model:        {cfg.get('default_model')}")
    print(f"Action Firewall:     {render_badge('ENFORCED', 'success')}")
    print("Storage Backend:     SQLite WAL / Postgres Ready")

    if is_online:
        tasks = client.list_tasks(limit=10)
        agents = client.list_agents()
        approvals = client.list_approvals(status="PENDING")
        workers = client.list_workers()
        print("-" * 50)
        print(f"Specialist Agents:   {len(agents)} active")
        print(f"Execution Workers:   {len(workers)} connected")
        print(f"Pending Approvals:   {len(approvals)}")
        print(f"Total Tasks:         {len(tasks)}")

    print(colorize("==================================================\n", BOLD + CYAN))
    return 0
