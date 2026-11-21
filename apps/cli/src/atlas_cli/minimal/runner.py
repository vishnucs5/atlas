"""Minimal terminal interaction mode for ATLAS CLI.

Supports interactive REPL, streaming responses, markdown rendering,
syntax highlighting, tool indicators, diff previews, and explicit approval prompts.
"""

import os
import re
import sys
import time
from typing import Any

from atlas_coding.engine import CodingEngine
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer

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
    render_banner,
    render_diff,
)
from atlas_cli.sessions.manager import SessionManager


def highlight_code_block(code: str, language: str = "") -> str:
    """Syntax highlight code block using Pygments."""
    try:
        if language:
            lexer = get_lexer_by_name(language.strip(), stripall=True)
        else:
            lexer = guess_lexer(code)
        return highlight(code, lexer, TerminalFormatter()).rstrip()
    except Exception:
        # Fallback to cyan-colored code block
        return colorize(code, CYAN)


def render_terminal_markdown(text: str) -> str:
    """Render markdown with colored headers, lists, bold text, and syntax-highlighted code blocks."""

    # Format code blocks ```lang ... ```
    def _replace_code(match: re.Match) -> str:
        lang = match.group(1) or ""
        code = match.group(2)
        highlighted = highlight_code_block(code, lang)
        header = colorize(f"┌─[ {lang.upper() or 'CODE'} ]" + "─" * 40, DIM)
        footer = colorize("└" + "─" * 50, DIM)
        return f"\n{header}\n{highlighted}\n{footer}\n"

    formatted = re.sub(r"```([a-zA-Z0-9_\-\+]*)\n(.*?)```", _replace_code, text, flags=re.DOTALL)

    # Format headers #, ##, ###
    formatted = re.sub(r"^### (.*?)$", colorize(r"\1", BOLD + CYAN), formatted, flags=re.MULTILINE)
    formatted = re.sub(r"^## (.*?)$", colorize(r"\1", BOLD + GREEN), formatted, flags=re.MULTILINE)
    formatted = re.sub(r"^# (.*?)$", colorize(r"\1", BOLD + YELLOW), formatted, flags=re.MULTILINE)

    # Format bold **text**
    formatted = re.sub(r"\*\*(.*?)\*\*", colorize(r"\1", BOLD), formatted)

    # Format inline code `code`
    formatted = re.sub(r"`([^`]+)`", colorize(r"\1", CYAN), formatted)

    # Format bullet lists
    formatted = re.sub(
        r"^[*-] (.*?)$", f"  {colorize('•', CYAN)} " + r"\1", formatted, flags=re.MULTILINE
    )

    return formatted


def stream_text_chunks(text: str, chunk_delay: float = 0.01) -> None:
    """Stream text output to terminal simulating responsive model generation."""
    words = text.split(" ")
    for idx, w in enumerate(words):
        sys.stdout.write(w + (" " if idx < len(words) - 1 else ""))
        sys.stdout.flush()
        if chunk_delay > 0 and idx % 4 == 0:
            time.sleep(chunk_delay)
    sys.stdout.write("\n")
    sys.stdout.flush()


class MinimalREPL:
    """Interactive Minimal Conversation Engine."""

    def __init__(
        self,
        client: AtlasClient | None = None,
        session_id: str | None = None,
        repo_root: str | None = None,
    ) -> None:
        self.client = client or AtlasClient()
        self.sess_mgr = SessionManager()
        self.repo_root = repo_root or os.getcwd()
        self.engine = CodingEngine(repo_root=self.repo_root)

        if session_id:
            existing = self.sess_mgr.get_session(session_id)
            if existing:
                self.session = existing
                print(colorize(f"Resumed session: {session_id}", GREEN))
            else:
                self.session = self.sess_mgr.create_session(objective="Interactive Minimal Session")
        else:
            self.session = self.sess_mgr.create_session(objective="Interactive Minimal Session")

        if "messages" not in self.session:
            self.session["messages"] = []

    def print_welcome(self) -> None:
        """Display minimal session banner and keyboard shortcuts."""
        print(render_banner())
        print(
            f"{BOLD}ATLAS Minimal Terminal{RESET} | Session: {colorize(self.session['session_id'], CYAN)}"
        )
        print(f"Workspace: {colorize(self.repo_root, DIM)}")
        print(colorize("Type your objective or slash command (/help, /diff, /status, /exit).", DIM))
        print("-" * 72)

    def print_help(self) -> None:
        """Display available slash commands and shortcuts."""
        print(colorize("\n[MINIMAL MODE SHORTCUTS]", BOLD + CYAN))
        print(f"  {colorize('/help', BOLD)}              Display this command guide")
        print(f"  {colorize('/diff', BOLD)}              Preview unified git diff of working tree")
        print(
            f"  {colorize('/status', BOLD)}            Inspect workspace and git porcelain status"
        )
        print(f"  {colorize('/plan <goal>', BOLD)}       Synthesize structured engineering plan")
        print(
            f"  {colorize('/test', BOLD)}              Discover and execute repository test suite"
        )
        print(
            f"  {colorize('/approvals', BOLD)}         Inspect and authorize Action Firewall requests"
        )
        print(f"  {colorize('/sessions', BOLD)}          List recent sessions")
        print(f"  {colorize('/resume <id>', BOLD)}       Resume an existing session")
        print(f"  {colorize('/clear', BOLD)}             Clear terminal screen")
        print(f"  {colorize('/exit', BOLD)} or {colorize('/quit', BOLD)}    Exit minimal mode")
        print("-" * 72)

    def handle_file_change_summary(self, changes: list[Any]) -> None:
        """Render file change summary cards."""
        if not changes:
            return
        print(colorize(f"\nFiles Modified ({len(changes)}):", BOLD + GREEN))
        for c in changes:
            c_type = getattr(c, "change_type", "MODIFY")
            path = getattr(c, "path", str(c))
            added = getattr(c, "lines_added", 0)
            removed = getattr(c, "lines_removed", 0)
            hash_str = getattr(c, "after_hash", "")[:8]
            print(
                f"  {colorize(f'[{c_type}]', YELLOW)} {path} {colorize(f'+{added}/-{removed}', GREEN)} (SHA: {hash_str})"
            )

    def execute_prompt(self, prompt: str) -> None:
        """Dispatch an engineering turn through the real orchestration runtime."""
        self.session["messages"].append({"role": "user", "content": prompt})
        from atlas_cli.commands.coding import run_coding_task

        result = run_coding_task(prompt=prompt, repo_root=self.repo_root)
        self.session["messages"].append(
            {
                "role": "assistant",
                "content": "Orchestration completed."
                if result == 0
                else "Orchestration did not complete.",
            }
        )
        self.sess_mgr.save_session(self.session["session_id"], self.session)

    def run_loop(self) -> int:
        """Run interactive REPL loop."""
        self.print_welcome()

        while True:
            try:
                prompt = input(f"{BOLD}atlas> {RESET}").strip()
                if not prompt:
                    continue

                # Slash command routing
                if prompt in ("/exit", "/quit", "exit", "quit"):
                    print(colorize("Exiting ATLAS Minimal Mode.", DIM))
                    return 0

                if prompt == "/help":
                    self.print_help()
                    continue

                if prompt == "/clear":
                    os.system("cls" if os.name == "nt" else "clear")
                    self.print_welcome()
                    continue

                if prompt == "/diff":
                    diff_text = self.engine.git.diff()
                    if diff_text:
                        print(render_diff(diff_text))
                    else:
                        print(colorize("Working tree clean. Zero unstaged changes.", GREEN))
                    continue

                if prompt == "/status":
                    status = self.engine.git.status()
                    print(f"Current Branch: {colorize(status.branch, BOLD)}")
                    print(f"Working Tree Clean: {status.is_clean}")
                    if status.modified:
                        print(f"Modified: {', '.join(status.modified)}")
                    if status.untracked:
                        print(f"Untracked: {', '.join(status.untracked)}")
                    continue

                if prompt.startswith("/plan "):
                    goal = prompt[6:].strip()
                    from atlas_cli.commands.coding import run_plan

                    run_plan(goal=goal, repo_root=self.repo_root)
                    continue

                if prompt == "/test":
                    from atlas_cli.commands.coding import run_test

                    run_test(repo_root=self.repo_root)
                    continue

                if prompt == "/approvals":
                    from atlas_cli.commands.approval import run_approval_list

                    run_approval_list()
                    continue

                if prompt == "/sessions":
                    from atlas_cli.commands.sessions_cmd import run_sessions_list

                    run_sessions_list()
                    continue

                if prompt.startswith("/resume "):
                    s_id = prompt[8:].strip()
                    existing = self.sess_mgr.get_session(s_id)
                    if existing:
                        self.session = existing
                        print(colorize(f"Switched to session: {s_id}", GREEN))
                    else:
                        print(colorize(f"Session not found: {s_id}", RED))
                    continue

                # Normal prompt execution
                self.execute_prompt(prompt)

            except KeyboardInterrupt:
                # Ctrl+C cancels current interactive input without terminating background work
                print(
                    colorize(
                        "\n[Interrupt] Turn cancelled by operator. Durable background tasks preserved.",
                        YELLOW,
                    )
                )
            except EOFError:
                print(colorize("\nExiting ATLAS Minimal Mode.", DIM))
                return 0

        return 0


def run_minimal(
    objective: str | None = None,
    json_output: bool = False,
    session_id: str | None = None,
    client: AtlasClient | None = None,
) -> int:
    """Execute task in minimal headless mode or launch interactive minimal REPL."""
    # 1. Non-interactive input from stdin or argument
    is_not_tty = hasattr(sys.stdin, "isatty") and not sys.stdin.isatty()
    if not objective and is_not_tty:
        try:
            stdin_text = sys.stdin.read().strip()
            if stdin_text:
                objective = stdin_text
        except (OSError, ValueError, AttributeError):
            pass

    if not objective and is_not_tty:
        print("Error: Objective required for minimal execution.", file=sys.stderr)
        return 1

    # 2. If objective supplied -> single-shot execution
    if objective:
        cli = client or AtlasClient()
        is_complex = any(k in objective.lower() for k in ["dag", "multi-agent", "specialist"])
        if is_complex:
            result = cli.submit_multi_agent_dag(objective, execute_async=False)
        else:
            result = cli.submit_task(objective, wait=True)

        if "error" in result:
            if result.get("offline") or (
                hasattr(cli, "is_server_online") and not cli.is_server_online()
            ):
                from atlas_cli.commands.coding import run_coding_task

                return run_coding_task(prompt=objective, repo_root=os.getcwd())
            print(colorize(f"FAILED: {result['error']}", RED), file=sys.stderr)
            return 1

        if json_output:
            import json

            print(json.dumps(result, indent=2))
        else:
            status = result.get("status", "COMPLETED")
            task_id = result.get("task_id", "")
            output = (
                result.get("metadata", {}).get("output") or result.get("message") or "Completed"
            )
            print(f"[{colorize(status, GREEN)}] {task_id}: {output}")
        return 0

    # 3. Interactive REPL mode
    repl = MinimalREPL(client=client, session_id=session_id)
    return repl.run_loop()
