"""Conversation rendering, streaming, activity badges, and approval cards."""

from __future__ import annotations

import re
import sys
import time
from typing import Any

from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer

from atlas_cli.rendering.formatters import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    YELLOW,
    colorize,
    render_badge,
)


def highlight_code_block(code: str, language: str = "") -> str:
    """Syntax highlight code block using Pygments with fallback."""
    try:
        if language:
            lexer = get_lexer_by_name(language.strip(), stripall=True)
        else:
            lexer = guess_lexer(code)
        return highlight(code, lexer, TerminalFormatter()).rstrip()
    except Exception:
        return colorize(code, CYAN)


def render_markdown(text: str) -> str:
    """Render markdown with headers, bold, inline code, and syntax-highlighted blocks."""

    def _replace_code(match: re.Match) -> str:
        lang = match.group(1) or ""
        code = match.group(2)
        highlighted = highlight_code_block(code, lang)
        header = colorize(f"┌─[ {lang.upper() or 'CODE'} ]" + "─" * 40, DIM)
        footer = colorize("└" + "─" * 50, DIM)
        return f"\n{header}\n{highlighted}\n{footer}\n"

    formatted = re.sub(r"```([a-zA-Z0-9_\-\+]*)\n(.*?)```", _replace_code, text, flags=re.DOTALL)
    formatted = re.sub(r"^### (.*?)$", colorize(r"\1", BOLD + CYAN), formatted, flags=re.MULTILINE)
    formatted = re.sub(r"^## (.*?)$", colorize(r"\1", BOLD + GREEN), formatted, flags=re.MULTILINE)
    formatted = re.sub(r"^# (.*?)$", colorize(r"\1", BOLD + YELLOW), formatted, flags=re.MULTILINE)
    formatted = re.sub(r"\*\*(.*?)\*\*", colorize(r"\1", BOLD), formatted)
    formatted = re.sub(r"`([^`]+)`", colorize(r"\1", CYAN), formatted)
    formatted = re.sub(
        r"^[*-] (.*?)$", f"  {colorize('•', CYAN)} " + r"\1", formatted, flags=re.MULTILINE
    )
    return formatted


def stream_markdown(text: str, delay: float = 0.008) -> None:
    """Stream response smoothly to stdout."""
    formatted = render_markdown(text)
    words = formatted.split(" ")
    for idx, w in enumerate(words):
        sys.stdout.write(w + (" " if idx < len(words) - 1 else ""))
        sys.stdout.flush()
        if delay > 0 and idx % 4 == 0:
            time.sleep(delay)
    sys.stdout.write("\n")
    sys.stdout.flush()


class ConversationRenderer:
    """Renders conversation turns, compact tool activities, diffs, and approvals."""

    @staticmethod
    def render_user_prompt(prompt: str) -> str:
        """Render user input line cleanly with prompt glyph."""
        return f"\n{colorize('›', BOLD + CYAN)} {colorize(prompt, BOLD)}\n"

    @staticmethod
    def render_activity(
        action: str,
        detail: str = "",
        status: str = "RUNNING",
        duration_ms: float | None = None,
    ) -> str:
        """Render a concise activity item adhering to Section 4.

        Examples:
          • Exploring project files (40 files indexed)
          • Reading apps/api/src/auth.py
          • Running pytest (22 passed) [0.4s]
        """
        if status == "RUNNING":
            bullet = colorize("•", CYAN)
        elif status == "SUCCESS":
            bullet = colorize("✓", GREEN)
        elif status == "FAILED":
            bullet = colorize("✗", RED)
        elif status == "PENDING":
            bullet = colorize("!", YELLOW)
        else:
            bullet = colorize("•", DIM)

        dur_str = (
            f" {colorize(f'[{duration_ms / 1000.0:.2f}s]', DIM)}" if duration_ms is not None else ""
        )
        detail_str = f" {colorize(detail, DIM)}" if detail else ""

        return f"  {bullet} {colorize(action, BOLD)}{detail_str}{dur_str}"

    @staticmethod
    def render_file_changes(changes: list[Any]) -> str:
        """Render inline file-change summary adhering to Section 6."""
        if not changes:
            return ""
        lines = [f"\n{colorize(f'Files modified ({len(changes)}):', BOLD)}"]
        for c in changes:
            c_type = getattr(c, "change_type", "MODIFY")
            path = getattr(c, "path", str(c))
            added = getattr(c, "lines_added", 0)
            removed = getattr(c, "lines_removed", 0)
            symbol = "+" if c_type == "CREATE" else ("~" if c_type == "MODIFY" else "-")
            color = GREEN if symbol == "+" else (YELLOW if symbol == "~" else RED)
            lines.append(
                f"  {colorize(symbol, color + BOLD)} {path} {colorize(f'(+{added} / -{removed})', DIM)}"
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def render_approval_card(approval_req: dict[str, Any]) -> str:
        """Render high-visibility contextual approval block adhering to Section 5."""
        action = approval_req.get("action", approval_req.get("action_type", "Execute action"))
        target = approval_req.get("target", "Workspace")
        params = approval_req.get("parameters", {})
        cmd = params.get("command") or params.get("path") or str(params)
        risk = approval_req.get("risk_level", "HIGH")
        risk_badge = render_badge(risk, "danger" if risk in ("HIGH", "CRITICAL") else "warning")

        width = 68
        border_top = "┌" + "─" * (width - 2) + "┐"
        border_bot = "└" + "─" * (width - 2) + "┘"

        card = [
            colorize(border_top, YELLOW),
            f"│ {colorize('ATLAS wants permission to execute:', BOLD + YELLOW):<{width - 3}} │",
            f"│   {colorize('Action:', BOLD)}  {action:<{width - 13}} │",
            f"│   {colorize('Target:', BOLD)}  {str(target):<{width - 13}} │",
            f"│   {colorize('Detail:', BOLD)}  {str(cmd)[: width - 15]:<{width - 13}} │",
            f"│   {colorize('Risk:', BOLD)}    {risk_badge:<{width - 11}} │",
            f"│{' ' * (width - 2)}│",
            f"│ {colorize('Options:', BOLD):<{width - 3}} │",
            f"│   {colorize('[A]', BOLD + GREEN)} Approve   "
            f"{colorize('[D]', BOLD + RED)} Deny   "
            f"{colorize('[V]', BOLD + CYAN)} View details   "
            f"{colorize('[C]', BOLD + DIM)} Cancel{' ' * 13}│",
            colorize(border_bot, YELLOW),
        ]
        return "\n".join(card)
