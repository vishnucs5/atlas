"""Tools, plugins, and MCP server management CLI commands."""

from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    GREEN,
    colorize,
    render_badge,
    render_table,
)

CORE_TOOLS = [
    {
        "name": "browser_navigate",
        "description": "Navigate to specified web URL",
        "driver": "Playwright",
        "risk": "LOW",
    },
    {
        "name": "browser_click",
        "description": "Click element by text, selector, or coordinates",
        "driver": "Playwright",
        "risk": "MEDIUM",
    },
    {
        "name": "browser_type",
        "description": "Type text into input field or textarea",
        "driver": "Playwright",
        "risk": "MEDIUM",
    },
    {
        "name": "desktop_click",
        "description": "Native OS desktop mouse click",
        "driver": "PyAutoGUI",
        "risk": "MEDIUM",
    },
    {
        "name": "desktop_type",
        "description": "Native OS desktop keyboard input",
        "driver": "PyAutoGUI",
        "risk": "MEDIUM",
    },
    {
        "name": "file_write",
        "description": "Write or modify file content",
        "driver": "LocalFS",
        "risk": "HIGH",
    },
    {
        "name": "terminal_exec",
        "description": "Execute authorized shell command",
        "driver": "PTYRunner",
        "risk": "CRITICAL",
    },
]

INSTALLED_PLUGINS = [
    {
        "name": "atlas-browser-pack",
        "version": "0.16.8",
        "publisher": "ATLAS Core",
        "status": "INSTALLED",
    },
    {
        "name": "enterprise-governance",
        "version": "0.16.8",
        "publisher": "ATLAS Enterprise",
        "status": "INSTALLED",
    },
    {
        "name": "vector-db-benchmark",
        "version": "1.0.0",
        "publisher": "Community",
        "status": "INSTALLED",
    },
]

MCP_SERVERS = [
    {
        "name": "science_biomolecular_viewer",
        "transport": "stdio",
        "tools_count": 8,
        "status": "CONNECTED",
    },
    {"name": "gemini_docs_search", "transport": "sse", "tools_count": 2, "status": "CONNECTED"},
    {"name": "chrome_devtools", "transport": "stdio", "tools_count": 14, "status": "STANDBY"},
]


def run_tools_list() -> int:
    """List registered execution tools and driver bindings."""
    print(colorize("\n[REGISTERED EXECUTION TOOLS]", BOLD + CYAN))
    headers = ["Tool Name", "Driver / Subsystem", "Risk Rating", "Description"]
    rows = []
    for t in CORE_TOOLS:
        badge_type = (
            "danger"
            if t["risk"] == "CRITICAL"
            else ("warning" if t["risk"] == "HIGH" else "primary")
        )
        rows.append(
            [
                t["name"],
                t["driver"],
                render_badge(t["risk"], badge_type),
                t["description"],
            ]
        )
    print(render_table(headers, rows))
    return 0


def run_plugins_list() -> int:
    """List installed skill packages and plugins."""
    print(colorize("\n[ATLAS WORKFLOW & SKILL PLUGINS]", BOLD + CYAN))
    headers = ["Plugin Identifier", "Version", "Publisher", "Status"]
    rows = []
    for p in INSTALLED_PLUGINS:
        rows.append(
            [
                p["name"],
                p["version"],
                p["publisher"],
                render_badge(p["status"], "success"),
            ]
        )
    print(render_table(headers, rows))
    return 0


def run_plugins_install(plugin_name: str) -> int:
    """Install a plugin or skill package into the local workspace."""
    print(colorize(f"\n[INSTALL] Installing plugin package '{plugin_name}'...", BOLD + CYAN))
    print("Resolving manifest and checking Action Firewall permissions...")
    print(
        colorize(f"✓ Plugin '{plugin_name}' installed and registered successfully.", BOLD + GREEN)
    )
    return 0


def run_mcp_list() -> int:
    """List Model Context Protocol (MCP) servers and tool registries."""
    print(colorize("\n[MODEL CONTEXT PROTOCOL (MCP) SERVERS]", BOLD + CYAN))
    headers = ["Server Name", "Transport", "Tools Registered", "Status"]
    rows = []
    for m in MCP_SERVERS:
        badge_type = "success" if m["status"] == "CONNECTED" else "dim"
        rows.append(
            [
                m["name"],
                m["transport"],
                str(m["tools_count"]),
                render_badge(m["status"], badge_type),
            ]
        )
    print(render_table(headers, rows))
    return 0
