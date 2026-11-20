"""Prompt composer, interactive slash menu, and command dispatcher for full-screen TUI."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import PromptSession
from prompt_toolkit.styles import Style

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
    "/models": "List, refresh, select, or configure free model providers",
    "/run": "Dispatch an objective through the full agent orchestration runtime",
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


class SlashCompleter(Completer):
    """Floating autocomplete menu for slash commands appearing directly above input."""

    COMMANDS = [
        ("/help", "Display interactive command guide and shortcuts"),
        ("/plan", "Synthesize execution plan without modifying files"),
        ("/run", "Dispatch a task through model, firewall, driver, and verification"),
        ("/test", "Discover and execute repository test suites"),
        ("/review", "Perform Action Firewall and git diff review"),
        ("/status", "Inspect workspace, git porcelain, and health"),
        ("/approvals", "Review and decide pending authorization requests"),
        ("/exit", "Exit ATLAS conversation mode"),
    ]

    def get_completions(self, document: Any, complete_event: Any) -> Any:
        text = document.text_before_cursor
        if text.startswith("/"):
            for cmd, desc in self.COMMANDS:
                if cmd.startswith(text):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=cmd,
                        display_meta=desc,
                    )


class PromptComposer:
    """Handles rounded container input box, floating slash menu, and persistent footer."""

    def __init__(
        self,
        repo_name: str = "workspace",
        branch: str = "main",
        model: str = "openrouter/free",
    ) -> None:
        self.history: list[str] = []
        self.repo_name = repo_name
        self.branch = branch
        self.model = model
        self._session: PromptSession[str] | None = None

    def update_context(self, repo_name: str, branch: str, model: str) -> None:
        """Update context displayed in the persistent bottom footer."""
        self.repo_name = repo_name
        self.branch = branch
        self.model = model

    def _is_interactive(self) -> bool:
        """Verify whether stdout and stdin are attached to an interactive console."""
        if not hasattr(sys.stdin, "isatty") or not sys.stdin.isatty():
            return False
        if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
            return False
        return True

    def _get_bottom_toolbar(self) -> FormattedText:
        """Generate persistent 2-line status footer for prompt_toolkit."""
        dir_icon = "📁" if sys.platform != "win32" or os.environ.get("WT_SESSION") else "[DIR]"
        branch_icon = (
            "🔀" if sys.platform != "win32" or os.environ.get("WT_SESSION") else "[BRANCH]"
        )
        model_icon = "⚙" if sys.platform != "win32" or os.environ.get("WT_SESSION") else "[MODEL]"

        line1 = f" {dir_icon} {self.repo_name}  │  {branch_icon} {self.branch}  │  {model_icon} {self.model}"
        line2 = " ? shortcuts  •  / commands  •  Esc cancel  •  Ctrl+C exit"

        return FormattedText(
            [
                ("class:bottom-toolbar", f"{line1}\n{line2}"),
            ]
        )

    def prompt(self) -> str | None:
        """Read prompt with rounded input box container, floating slash menu, and footer."""
        if not self._is_interactive():
            return self._prompt_fallback()

        try:
            term_cols = shutil.get_terminal_size((80, 24)).columns
            width = min(term_cols, 96)
            top_border = "╭" + "─" * (width - 2) + "╮"
            bot_border = "╰" + "─" * (width - 2) + "╯"

            # Dual-accent TrueColor palette for prompt_toolkit
            pt_style = Style.from_dict(
                {
                    "border": "#F97316 bold",  # Warm Coral active focus
                    "prompt": "#38BDF8 bold",  # Sky Cyan
                    "placeholder": "#64748B",  # Slate Gray
                    "bottom-toolbar": "#64748B",  # Slate Gray
                    "completion-menu": "bg:#0D1117 #F1F5F9",
                    "completion-menu.completion": "#F1F5F9",
                    "completion-menu.completion.current": "bg:#38BDF8 #0D1117 bold",
                    "completion-menu.meta": "#64748B",
                }
            )

            if self._session is None:
                self._session = PromptSession(
                    completer=SlashCompleter(),
                    complete_while_typing=True,
                    style=pt_style,
                )

            # Print active top container border in Warm Coral #F97316
            print(f"\033[38;2;249;115;22m{top_border}\033[0m")

            user_input = self._session.prompt(
                message=FormattedText(
                    [
                        ("class:border", "│ "),
                        ("class:prompt", "> "),
                    ]
                ),
                placeholder=FormattedText(
                    [
                        ("class:placeholder", "What would you like to build today?"),
                    ]
                ),
                bottom_toolbar=self._get_bottom_toolbar,
            ).strip()

            # Print active bottom container border in Warm Coral #F97316
            print(f"\033[38;2;249;115;22m{bot_border}\033[0m")

            if user_input:
                self.history.append(user_input)
            return user_input

        except (KeyboardInterrupt, EOFError):
            return None
        except Exception:
            return self._prompt_fallback()

    def _prompt_fallback(self) -> str | None:
        """Graceful standard input fallback for non-TTY / testing environments."""
        try:
            first_line = input(f"{BOLD}{CYAN}› {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            return None

        if not first_line:
            return ""

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
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("/exit", "/quit"):
            print(colorize("Exiting ATLAS. Goodbye!", BOLD + GREEN))
            return False

        if cmd == "/help":
            print(PromptComposer.get_command_help())
            return True

        if cmd == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
            print(self.app.header.render_welcome())
            return True

        if cmd == "/inspector":
            self.app.open_inspector()
            return True

        if cmd == "/compact":
            self.app.compact_session()
            return True

        # Operations delegating to CLI commands
        if cmd == "/status":
            from atlas_cli.commands.governance import run_status

            run_status()
            return True

        if cmd == "/permissions":
            from atlas_cli.commands.governance import run_permissions

            run_permissions()
            return True

        if cmd == "/approvals":
            from atlas_cli.commands.approval import run_approval_list

            run_approval_list()
            return True

        if cmd == "/agents":
            from atlas_cli.commands.agents import run_agents_list

            run_agents_list()
            return True

        if cmd == "/sessions":
            from atlas_cli.commands.sessions_cmd import run_sessions_list

            run_sessions_list()
            return True

        if cmd in ("/model", "/models"):
            from atlas_cli.commands.models import (
                run_models_configure,
                run_models_list,
                run_models_refresh,
                run_models_remove,
                run_models_test,
                run_models_use,
            )

            action, _, value = arg.partition(" ")
            if action == "use" and value:
                run_models_use(value.strip())
            elif action == "configure":
                run_models_configure(value.strip() or None)
            elif action == "test" and value:
                run_models_test(value.strip())
            elif action == "remove" and value:
                run_models_remove(value.strip())
            elif action == "refresh":
                run_models_refresh()
            elif arg:
                run_models_use(arg)
            else:
                run_models_list()
            return True

        if cmd == "/plan":
            if not arg:
                print(colorize("Usage: /plan <goal>", YELLOW))
            else:
                from atlas_cli.commands.coding import run_plan

                run_plan(goal=arg)
            return True

        if cmd == "/run":
            if not arg:
                print(colorize("Usage: /run <objective>", YELLOW))
            else:
                from atlas_cli.commands.coding import run_coding_task

                run_coding_task(prompt=arg, repo_root=self.repo_root)
            return True

        if cmd == "/review":
            from atlas_cli.commands.coding import run_review

            run_review(diff=True)
            return True

        if cmd == "/debug":
            from atlas_cli.commands.coding import run_debug

            run_debug()
            return True

        if cmd == "/test":
            from atlas_cli.commands.coding import run_test

            run_test()
            return True

        print(colorize(f"Unknown command: '{cmd}'. Type /help for available commands.", RED))
        return True
