"""Prompt composer, history, and slash command dispatcher for conversation-first UI."""

from __future__ import annotations

import os
from typing import Any

from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    RESET,
    YELLOW,
    colorize,
)

SLASH_COMMANDS = {
    "/help": "Display interactive command guide and shortcuts",
    "/status": "Inspect workspace, git porcelain, and platform status",
    "/model": "Display or switch active model provider",
    "/models": "List available model providers and capabilities",
    "/plan": "Synthesize a multi-step execution plan without modifying files",
    "/review": "Perform Action Firewall and git diff code review",
    "/debug": "Diagnose runtime errors and environment anomalies",
    "/test": "Discover and execute repository test suites",
    "/permissions": "Display Action Firewall security boundary rules",
    "/approvals": "Review and decide pending authorization requests",
    "/agents": "List the 11 autonomous specialist agents and roles",
    "/sessions": "List and switch recent conversation sessions",
    "/inspector": "Open the 8-panel advanced diagnostic inspector",
    "/compact": "Compact session event history to optimize context",
    "/clear": "Clear screen buffer without losing conversation history",
    "/exit": "Exit ATLAS conversation mode",
    "/quit": "Exit ATLAS conversation mode",
}


class PromptComposer:
    """Handles multiline prompt composition, history, and slash command validation."""

    def __init__(self) -> None:
        self.history: list[str] = []

    def prompt(self) -> str | None:
        """Read single or multiline input from user.

        Supports line continuation using trailing backslash '\\' or empty line completion.
        """
        try:
            first_line = input(f"{BOLD}{CYAN}› {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            return None

        if not first_line:
            return ""

        # Multiline check: if line ends with '\', continue reading
        if first_line.endswith("\\"):
            lines = [first_line[:-1].strip()]
            print(colorize("  ... (Enter blank line to finish)", DIM))
            while True:
                try:
                    next_line = input(f"{DIM}  ... {RESET}")
                    if not next_line.strip():
                        break
                    if next_line.strip().endswith("\\"):
                        lines.append(next_line.strip()[:-1].strip())
                    else:
                        lines.append(next_line.strip())
                except (KeyboardInterrupt, EOFError):
                    break
            full_prompt = " ".join(lines).strip()
        else:
            full_prompt = first_line

        if full_prompt:
            self.history.append(full_prompt)

        return full_prompt

    @staticmethod
    def is_slash_command(prompt: str) -> bool:
        """Check whether input is a slash command."""
        return prompt.strip().startswith("/")

    @staticmethod
    def get_command_help() -> str:
        """Generate formatted slash command palette adhering to Section 8."""
        lines = [
            f"{BOLD}AVAILABLE SLASH COMMANDS{RESET}",
            colorize("─" * 68, DIM),
        ]
        for cmd, desc in sorted(SLASH_COMMANDS.items()):
            if cmd == "/quit":
                continue
            lines.append(f"  {colorize(f'{cmd:<14}', BOLD + CYAN)} {colorize(desc, DIM)}")
        lines.append(colorize("─" * 68, DIM))
        lines.append(
            f"{DIM}Keyboard Shortcuts: Enter to submit · Shift+Enter/'\\' for newline · Ctrl+C to cancel turn{RESET}"
        )
        return "\n".join(lines)


class SlashCommandDispatcher:
    """Routes slash commands to existing ATLAS CLI application services."""

    def __init__(
        self,
        app: Any,
        repo_root: str | None = None,
    ) -> None:
        self.app = app
        self.repo_root = repo_root or os.getcwd()

    def dispatch(self, cmd_line: str) -> bool:
        """Execute slash command. Returns True to continue, False to exit."""
        parts = cmd_line.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("/exit", "/quit"):
            print(colorize("Exiting ATLAS. Goodbye!", DIM))
            return False

        if cmd == "/help":
            print(PromptComposer.get_command_help())
            return True

        if cmd == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
            print(self.app.header.render_welcome())
            return True

        if cmd == "/status":
            from atlas_cli.commands.governance import run_status

            run_status()
            return True

        if cmd in ("/model", "/models"):
            from atlas_cli.commands.models import run_models_list

            run_models_list()
            return True

        if cmd == "/plan":
            if not args:
                print(colorize("Usage: /plan <goal>", YELLOW))
            else:
                from atlas_cli.commands.coding import run_plan

                run_plan(goal=args, repo_root=self.repo_root)
            return True

        if cmd == "/review":
            from atlas_cli.commands.coding import run_review

            run_review(diff=True, repo_root=self.repo_root)
            return True

        if cmd == "/debug":
            from atlas_cli.commands.coding import run_debug

            run_debug(repo_root=self.repo_root)
            return True

        if cmd == "/test":
            from atlas_cli.commands.coding import run_test

            run_test(repo_root=self.repo_root)
            return True

        if cmd == "/permissions":
            from atlas_cli.commands.governance import run_permissions

            run_permissions()
            return True

        if cmd == "/approvals":
            from atlas_cli.approvals.interactive import run_interactive_approvals

            run_interactive_approvals(self.app.client)
            return True

        if cmd == "/agents":
            from atlas_cli.commands.agents import run_agents_list

            run_agents_list()
            return True

        if cmd == "/sessions":
            from atlas_cli.commands.sessions_cmd import run_sessions_list

            run_sessions_list()
            return True

        if cmd == "/inspector":
            self.app.open_inspector()
            return True

        if cmd == "/compact":
            if hasattr(self.app, "compact_session"):
                self.app.compact_session()
            else:
                print(colorize("Session history compacted.", GREEN))
            return True

        # Unknown command handling
        print(
            colorize(
                f"Unknown command: '{cmd}'. Type {colorize('/help', BOLD)} for available commands.",
                RED,
            )
        )
        return True
