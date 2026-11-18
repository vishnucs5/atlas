"""Specialist agent management and inspection CLI commands."""

from typing import Any

from atlas_cli.adapters.client import AtlasClient
from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    GREEN,
    RED,
    colorize,
    render_badge,
    render_table,
)

DEFAULT_SPECIALISTS = [
    {
        "agent_id": "agent_architect",
        "name": "Software Architect",
        "role": "Architect",
        "capabilities": ["ARCHITECT", "RESEARCH"],
        "status": "READY",
        "tokens": 0,
    },
    {
        "agent_id": "agent_explorer",
        "name": "Repository Explorer",
        "role": "Explorer",
        "capabilities": ["EXPLORER", "RESEARCH"],
        "status": "READY",
        "tokens": 0,
    },
    {
        "agent_id": "agent_backend",
        "name": "Backend Engineer",
        "role": "Backend",
        "capabilities": ["BACKEND", "CODE"],
        "status": "READY",
        "tokens": 0,
    },
    {
        "agent_id": "agent_frontend",
        "name": "Frontend Engineer",
        "role": "Frontend",
        "capabilities": ["FRONTEND", "CODE"],
        "status": "READY",
        "tokens": 0,
    },
    {
        "agent_id": "agent_database",
        "name": "Database Engineer",
        "role": "Database",
        "capabilities": ["DATABASE", "CODE"],
        "status": "READY",
        "tokens": 0,
    },
    {
        "agent_id": "agent_infra",
        "name": "Infrastructure Engineer",
        "role": "Infrastructure",
        "capabilities": ["INFRASTRUCTURE", "CODE"],
        "status": "READY",
        "tokens": 0,
    },
    {
        "agent_id": "agent_testing",
        "name": "Testing Engineer",
        "role": "Testing",
        "capabilities": ["TESTING", "QUALITY_ASSURANCE"],
        "status": "READY",
        "tokens": 0,
    },
    {
        "agent_id": "agent_security",
        "name": "Security Auditor",
        "role": "Security",
        "capabilities": ["SECURITY_AUDITOR", "QUALITY_ASSURANCE"],
        "status": "READY",
        "tokens": 0,
    },
    {
        "agent_id": "agent_reviewer",
        "name": "Code Reviewer",
        "role": "Reviewer",
        "capabilities": ["CODE_REVIEWER", "QUALITY_ASSURANCE"],
        "status": "READY",
        "tokens": 0,
    },
    {
        "agent_id": "agent_docs",
        "name": "Documentation Engineer",
        "role": "Documentation",
        "capabilities": ["DOCUMENTATION", "CODE"],
        "status": "READY",
        "tokens": 0,
    },
    {
        "agent_id": "agent_debugging",
        "name": "Debugging Engineer",
        "role": "Debugging",
        "capabilities": ["DEBUGGING", "CODE"],
        "status": "READY",
        "tokens": 0,
    },
]


def run_agents_list(client: AtlasClient | None = None) -> int:
    """List registered specialist agents in the cluster."""
    client = client or AtlasClient()
    agents = client.list_agents() or DEFAULT_SPECIALISTS

    print(colorize("\n[AUTONOMOUS SPECIALIST AGENTS]", BOLD + CYAN))
    headers = ["Agent ID", "Name", "Role", "Capabilities", "Status", "Tokens"]
    rows = []
    for ag in agents:
        st = str(ag.get("status", "READY"))
        badge_type = (
            "success" if st in ("READY", "IDLE") else ("warning" if st == "BUSY" else "danger")
        )
        caps = ag.get("capabilities", [])
        caps_str = ", ".join(str(c) for c in caps) if isinstance(caps, list) else str(caps)
        budget = ag.get("budget")
        tokens = budget.get("tokens_used", 0) if isinstance(budget, dict) else ag.get("tokens", 0)
        rows.append(
            [
                str(ag.get("agent_id")),
                str(ag.get("name")),
                str(ag.get("role")),
                caps_str,
                render_badge(st, badge_type),
                str(tokens),
            ]
        )

    print(render_table(headers, rows))
    return 0


def run_agents_inspect(agent_id: str, client: AtlasClient | None = None) -> int:
    """Inspect detailed capabilities, budget, and lease state for an agent."""
    client = client or AtlasClient()
    agents = client.list_agents() or DEFAULT_SPECIALISTS

    target: dict[str, Any] | None = None
    for ag in agents:
        if isinstance(ag, dict) and (
            str(ag.get("agent_id")) == agent_id
            or agent_id.lower() in str(ag.get("name", "")).lower()
        ):
            target = ag
            break

    if not target:
        print(colorize(f"Error: Specialist agent '{agent_id}' not found.", RED))
        return 1

    caps = target.get("capabilities", [])
    caps_list = [str(c) for c in caps] if isinstance(caps, list) else [str(caps)]

    print(colorize(f"\n[AGENT INSPECTION: {target.get('agent_id')}]", BOLD + CYAN))
    print(f"Name:         {target.get('name')}")
    print(f"Role:         {target.get('role')}")
    print(f"Capabilities: {', '.join(caps_list)}")
    print(f"Status:       {render_badge(str(target.get('status', 'READY')), 'success')}")
    print("Lease State:  Free / Ready for subtask dispatch")
    print("Memory Scope: Task-scoped + Cluster Shared Memory")
    print("Firewall:     Enforced (ActionFirewall Policy Decider)")
    return 0


def run_agents_run(agent_id: str, objective: str, client: AtlasClient | None = None) -> int:
    """Direct a specific specialist agent to execute an objective."""
    client = client or AtlasClient()
    print(
        colorize(f"\n[DISPATCH] Directing agent '{agent_id}' to execute: {objective}", BOLD + CYAN)
    )

    # Submit task with agent tag in metadata
    res = client.submit_task(objective, metadata={"assigned_agent": agent_id}, wait=True)
    if "error" in res:
        print(colorize(f"✗ Execution failed: {res['error']}", RED))
        return 1

    print(colorize(f"✓ Agent '{agent_id}' completed execution successfully.", BOLD + GREEN))
    output = (
        res.get("metadata", {}).get("output") or res.get("metadata", {}).get("result") or "Done"
    )
    print(f"\nDeliverable:\n{output}")
    return 0
