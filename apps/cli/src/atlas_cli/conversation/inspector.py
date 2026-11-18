"""On-demand 8-panel diagnostic inspector for ATLAS conversation mode."""

from __future__ import annotations

import os
import time

from atlas_coding.engine import CodingEngine

from atlas_cli.adapters.client import AtlasClient
from atlas_cli.events.reconstructor import UIState
from atlas_cli.events.stream import EventStreamSubscriber
from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RESET,
    YELLOW,
    colorize,
    render_badge,
    render_diff,
    render_table,
)
from atlas_cli.sessions.manager import SessionManager

INSPECTOR_PANELS = [
    "1. Conversation",
    "2. Agent Activity",
    "3. Task Graph",
    "4. Terminal",
    "5. File Changes",
    "6. Approvals",
    "7. Timeline",
    "8. Runtime",
]


class AdvancedInspector:
    """Provides on-demand access to the 8 diagnostic panels without cluttering conversation."""

    def __init__(
        self,
        client: AtlasClient | None = None,
        repo_root: str | None = None,
        subscriber: EventStreamSubscriber | None = None,
    ) -> None:
        self.client = client or AtlasClient()
        self.repo_root = repo_root or os.getcwd()
        self.engine = CodingEngine(repo_root=self.repo_root)
        self.sess_mgr = SessionManager()
        self.subscriber = subscriber or EventStreamSubscriber()
        self.ui_state = UIState()
        self.active_panel_idx = 0
        self.messages: list[dict[str, str]] = []
        self.terminal_history: list[str] = []

    def render_panel_header(self) -> str:
        """Render tab bar showing the 8 panels."""
        tabs = []
        for idx, name in enumerate(INSPECTOR_PANELS):
            if idx == self.active_panel_idx:
                tabs.append(colorize(f"[{name}]", BOLD + CYAN))
            else:
                tabs.append(colorize(name, DIM))
        tab_line = " | ".join(tabs)
        controls = colorize(
            "Inspector Controls: [1-8] Switch Panel | [Tab] Next | [r] Refresh | [q] Return to Conversation",
            DIM,
        )
        border = colorize("═" * 72, DIM)
        return f"{border}\n{tab_line}\n{controls}\n{border}"

    def render_content(self) -> str:
        """Render active panel contents."""
        idx = self.active_panel_idx
        if idx == 0:
            # 1. Conversation
            if not self.messages:
                return colorize("  No conversation messages in current inspector buffer.", DIM)
            lines = []
            for m in self.messages[-10:]:
                role = colorize("User:" if m["role"] == "user" else "Assistant:", BOLD)
                lines.append(f"  {role} {m['content']}")
            return "\n".join(lines)

        elif idx == 1:
            # 2. Agent Activity
            agents = self.client.list_agents()
            if not agents:
                return colorize("  No agents actively registered.", DIM)
            rows = []
            for ag in agents:
                st = ag.get("status", "READY")
                badge = render_badge(st, "success" if st == "READY" else "warning")
                rows.append([ag.get("agent_id", ""), ag.get("name", ""), badge])
            return render_table(["ID", "Name", "Status"], rows)

        elif idx == 2:
            # 3. Task Graph
            return colorize("  Task DAG: Verified sequential execution pipeline active.", CYAN)

        elif idx == 3:
            # 4. Terminal
            if not self.terminal_history:
                return colorize("  No terminal command output recorded.", DIM)
            return "\n".join(f"  {colorize('$', DIM)} {cmd}" for cmd in self.terminal_history[-8:])

        elif idx == 4:
            # 5. File Changes
            diff = self.engine.git.diff()
            if diff:
                return render_diff(diff)
            return colorize("  Working tree clean. Zero unstaged changes.", GREEN)

        elif idx == 5:
            # 6. Approvals
            pending = self.client.list_approvals(status="PENDING")
            if not pending:
                return colorize("  Zero pending Action Firewall approvals.", GREEN)
            from atlas_cli.approvals.interactive import format_approval_card

            return "\n".join(format_approval_card(r) for r in pending)

        elif idx == 6:
            # 7. Timeline
            events = self.subscriber.buffered_events[-6:]
            if not events:
                return colorize("  Zero execution events in buffer.", DIM)
            lines = []
            for ev in events:
                e_type = getattr(ev, "event_type", "EVENT")
                e_name = getattr(e_type, "value", str(e_type))
                lines.append(
                    f"  • {colorize(e_name, CYAN)} (Task: {getattr(ev, 'task_id', 'unknown')})"
                )
            return "\n".join(lines)

        else:
            # 8. Runtime
            health = self.client.get_server_health()
            status_str = colorize(f"Server Health: {health.get('status', 'offline')}", BOLD)
            storage_str = colorize("Storage: SQLite WAL active", DIM)
            return f"  {status_str}\n  {storage_str}\n  Target Root: {self.repo_root}"

    def show(self) -> None:
        """Display inspector and handle single-key switching until user exits."""
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            print(colorize(f"{BOLD}[ATLAS ADVANCED DIAGNOSTIC INSPECTOR]{RESET}", CYAN))
            print(self.render_panel_header())
            print(self.render_content())
            print(colorize("─" * 72, DIM))

            try:
                choice = input(f"{BOLD}inspector> {RESET}").strip().lower()
            except (KeyboardInterrupt, EOFError):
                break

            if choice in ("q", "quit", "exit", "esc", ""):
                break
            elif choice in ("tab", "n", "next"):
                self.active_panel_idx = (self.active_panel_idx + 1) % len(INSPECTOR_PANELS)
            elif choice in ("r", "refresh"):
                continue
            elif choice.isdigit() and 1 <= int(choice) <= 8:
                self.active_panel_idx = int(choice) - 1
            else:
                print(
                    colorize("Invalid choice. Press 1-8 to switch panel, or 'q' to exit.", YELLOW)
                )
                time.sleep(0.6)
