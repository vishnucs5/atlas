"""Interactive Terminal User Interface (TUI) for ATLAS CLI."""

import os
import time

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
    render_banner,
    render_table,
)


def clear_screen() -> None:
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def run_tui(client: AtlasClient | None = None) -> int:
    """Run interactive Terminal User Interface loop."""
    client = client or AtlasClient()

    clear_screen()
    print(render_banner())
    print(colorize("Initializing ATLAS Interactive Terminal Dashboard...", CYAN))

    # Test server connection
    health = client.get_server_health()
    server_online = health.get("status") in ("ok", "healthy")

    while True:
        clear_screen()
        # Top Status Bar
        status_badge = (
            render_badge("ONLINE", "success")
            if server_online
            else render_badge("OFFLINE", "danger")
        )
        print(
            f"{BOLD}ATLAS Control Plane{RESET} | Status: {status_badge} | URL: {colorize(client.base_url, CYAN)}"
        )
        print("=" * 80)

        # Fetch live data
        tasks = client.list_tasks(limit=5)
        agents = client.list_agents()
        approvals = client.list_approvals(status="PENDING")
        workers = client.list_workers()

        # Summary KPIs
        print(
            f"Active Tasks: {colorize(str(len(tasks)), BOLD)} | Specialists: {colorize(str(len(agents)), CYAN)} | Workers: {colorize(str(len(workers)), GREEN)} | Pending Approvals: {colorize(str(len(approvals)), YELLOW if approvals else DIM)}"
        )
        print("-" * 80)

        # Specialist Agents Section
        print(colorize("\n[AUTONOMOUS SPECIALIST AGENTS]", BOLD + CYAN))
        if agents:
            ag_headers = ["Agent ID", "Name", "Role", "Capabilities", "Status", "Tokens"]
            ag_rows = []
            for ag in agents:
                st = ag.get("status", "READY")
                badge_type = (
                    "success"
                    if st in ("READY", "IDLE")
                    else ("warning" if st == "BUSY" else "danger")
                )
                ag_rows.append(
                    [
                        ag.get("agent_id"),
                        ag.get("name"),
                        ag.get("role"),
                        ", ".join(ag.get("capabilities", [])),
                        render_badge(st, badge_type),
                        str(ag.get("budget", {}).get("tokens_used", 0)),
                    ]
                )
            print(render_table(ag_headers, ag_rows))
        else:
            print(colorize("  No agents loaded or server offline.", DIM))

        # Recent Tasks Section
        print(colorize("\n[RECENT TASK FLEET & DELIVERABLES]", BOLD + GREEN))
        if tasks:
            t_headers = ["Task ID", "Objective", "Status", "Priority"]
            t_rows = []
            for t in tasks:
                st = t.get("status", "COMPLETED")
                badge_type = (
                    "success"
                    if st == "COMPLETED"
                    else ("warning" if st in ("WAITING_APPROVAL", "RUNNING") else "danger")
                )
                t_rows.append(
                    [
                        t.get("task_id"),
                        (t.get("objective") or "")[:40]
                        + ("..." if len(t.get("objective", "")) > 40 else ""),
                        render_badge(st, badge_type),
                        t.get("priority", "NORMAL"),
                    ]
                )
            print(render_table(t_headers, t_rows))
        else:
            print(colorize("  No active or completed tasks.", DIM))

        # Pending Approvals Section (if any)
        if approvals:
            print(colorize("\n[ACTION FIREWALL APPROVALS NEEDED]", BOLD + YELLOW))
            for a in approvals:
                print(
                    f"  * {a.get('request_id')}: {a.get('action_type')} (Risk: {a.get('risk_level')}) - {a.get('reason')}"
                )

        print("\n" + "=" * 80)
        print(
            f"Commands: [{colorize('run <prompt>', CYAN)}] Submit task | [{colorize('approvals', YELLOW)}] Authorize | [{colorize('r', GREEN)}] Refresh | [{colorize('q', RED)}] Quit"
        )

        try:
            cmd = input(f"{BOLD}atlas> {RESET}").strip()
            if not cmd:
                continue
            if cmd in ("q", "quit", "exit"):
                print("Exiting ATLAS TUI.")
                return 0
            elif cmd == "r":
                continue
            elif cmd == "approvals":
                from atlas_cli.approvals.interactive import run_interactive_approvals

                run_interactive_approvals(client)
                input("\nPress Enter to return to dashboard...")
            elif cmd.startswith("run "):
                prompt = cmd[4:].strip()
                print(colorize(f"\nDispatching task: '{prompt}'...", CYAN))
                if any(
                    k in prompt.lower() for k in ["dag", "multi-agent", "benchmark", "calculate"]
                ):
                    res = client.submit_multi_agent_dag(prompt)
                else:
                    res = client.submit_task(prompt, wait=True)
                print(colorize("✓ Task Completed:", GREEN))
                out = res.get("metadata", {}).get("output") or res.get("message") or str(res)
                print(f"\n{out}\n")
                input("Press Enter to continue...")
            else:
                print(f"Unknown command: '{cmd}'. Try 'run <prompt>', 'approvals', 'r', or 'q'.")
                time.sleep(1.5)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting ATLAS TUI.")
            return 0
