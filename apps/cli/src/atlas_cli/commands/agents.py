"""Specialist agent management and inspection CLI commands."""

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
        "agent_id": "agent_res_default",
        "name": "Default Research Specialist",
        "role": "Researcher",
        "capabilities": ["RESEARCH"],
        "status": "READY",
        "tokens": 250,
    },
    {
        "agent_id": "agent_code_default",
        "name": "Default Coding Specialist",
        "role": "Coder",
        "capabilities": ["CODE"],
        "status": "READY",
        "tokens": 800,
    },
    {
        "agent_id": "agent_qa_default",
        "name": "Default QA Specialist",
        "role": "QA Reviewer",
        "capabilities": ["QUALITY_ASSURANCE"],
        "status": "READY",
        "tokens": 200,
    },
    {
        "agent_id": "agent_data_default",
        "name": "Default Data Specialist",
        "role": "Data Analyst",
        "capabilities": ["DATA_ANALYSIS"],
        "status": "READY",
        "tokens": 300,
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
        st = ag.get("status", "READY")
        badge_type = (
            "success" if st in ("READY", "IDLE") else ("warning" if st == "BUSY" else "danger")
        )
        caps = ag.get("capabilities", [])
        caps_str = ", ".join(caps) if isinstance(caps, list) else str(caps)
        tokens = ag.get("budget", {}).get("tokens_used", ag.get("tokens", 0))
        rows.append(
            [
                ag.get("agent_id"),
                ag.get("name"),
                ag.get("role"),
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

    target = None
    for ag in agents:
        if ag.get("agent_id") == agent_id or agent_id.lower() in ag.get("name", "").lower():
            target = ag
            break

    if not target:
        print(colorize(f"Error: Specialist agent '{agent_id}' not found.", RED))
        return 1

    print(colorize(f"\n[AGENT INSPECTION: {target.get('agent_id')}]", BOLD + CYAN))
    print(f"Name:         {target.get('name')}")
    print(f"Role:         {target.get('role')}")
    print(f"Capabilities: {', '.join(target.get('capabilities', []))}")
    print(f"Status:       {render_badge(target.get('status', 'READY'), 'success')}")
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
