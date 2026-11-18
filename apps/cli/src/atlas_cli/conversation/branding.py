"""ATLAS Aegis Visual Identity and Branding Component.

Provides the original geometric Aegis emblem, wordmark, compact headers,
conversation markers, task completion badges, and graceful ASCII fallbacks.
"""

from __future__ import annotations

import os
import re
import shutil
import sys

VERSION = "0.16.8"

# Terminal Color Codes
BOLD = "\033[1m"
DIM = "\033[90m"
RESET = "\033[0m"
CYAN = "\033[96m"  # Electric cyan
TEAL = "\033[36m"  # Deep teal
WHITE = "\033[97m"  # High-contrast white
GREEN = "\033[92m"  # Success green
YELLOW = "\033[93m"  # Star gold / Accent yellow

ANSI_REGEX = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences to compute exact visible character count."""
    return ANSI_REGEX.sub("", text)


def pad_visible(text: str, width: int) -> str:
    """Pad string with trailing spaces based on its visible width without ANSI codes."""
    vis_len = len(strip_ansi(text))
    pad = max(0, width - vis_len)
    return text + (" " * pad)


class AegisBranding:
    """Reusable presentation component for ATLAS Aegis visual identity."""

    def __init__(
        self,
        force_unicode: bool | None = None,
        force_color: bool | None = None,
    ) -> None:
        self._force_unicode = force_unicode
        self._force_color = force_color

    def supports_unicode(self) -> bool:
        """Check whether current terminal environment supports UTF-8 Unicode glyphs."""
        if self._force_unicode is not None:
            return self._force_unicode
        if os.environ.get("ATLAS_NO_UNICODE", "").lower() in ("1", "true", "yes"):
            return False
        # Check standard output encoding
        encoding = getattr(sys.stdout, "encoding", "") or ""
        if encoding.lower() in ("utf-8", "utf8", "utf_8"):
            return True
        # On Windows, Windows Terminal or modern consoles support UTF-8
        if sys.platform == "win32":
            if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"):
                return True
        return False

    def supports_color(self) -> bool:
        """Check whether terminal environment supports ANSI escape sequences."""
        if self._force_color is not None:
            return self._force_color
        if os.environ.get("NO_COLOR") or os.environ.get("ATLAS_NO_COLOR", "").lower() in (
            "1",
            "true",
            "yes",
        ):
            return False
        if os.environ.get("TERM") == "dumb":
            return False
        if hasattr(sys.stdout, "isatty") and not sys.stdout.isatty():
            return False
        return True

    def colorize(self, text: str, style: str) -> str:
        """Apply ANSI color styling if supported, otherwise return plain text."""
        if not self.supports_color():
            return text
        return f"{style}{text}{RESET}"

    def get_terminal_width(self, default: int = 80) -> int:
        """Retrieve current terminal width."""
        try:
            return shutil.get_terminal_size((default, 24)).columns
        except Exception:
            return default

    # -------------------------------------------------------------------------
    # Emblem Geometry
    # -------------------------------------------------------------------------

    def get_emblem_lines(self) -> list[str]:
        """Return 6-line Aegis emblem with orbital ring, A-frame, and compass star."""
        use_unicode = self.supports_unicode()
        use_color = self.supports_color()

        if not use_unicode:
            # ASCII Fallback Emblem
            if not use_color:
                return [
                    "        ^     +",
                    "       / \\   /",
                    "     +/---\\--+",
                    "   ( |  ^  | )",
                    "    +\\--+--/+-+",
                    "     (--+--)",
                ]
            c_white = WHITE + BOLD
            c_cyan = CYAN
            c_teal = TEAL
            c_star = YELLOW + BOLD
            rst = RESET
            return [
                f"        {c_white}^{rst}     {c_star}+{rst}",
                f"       {c_white}/ \\{rst}   {c_cyan}/{rst}",
                f"     {c_teal}+{c_white}/---\\--{c_teal}+{rst}",
                f"   {c_teal}( {c_white}|  ^  |{c_teal} ){rst}",
                f"    {c_teal}+{c_white}\\--+--/{c_teal}+-+{rst}",
                f"     {c_teal}(--+--{c_teal}){rst}",
            ]

        # Unicode Emblem
        if not use_color:
            return [
                "        ▲     ✦",
                "       ╱ ╲   ╭╯",
                "     ╭╱───╲──╯",
                "   ❪ │  ▲  │ ❫",
                "    ╰╲─┬─┬─╱─╮",
                "     ❪─┼─┼─❫",
            ]

        c_white = WHITE + BOLD
        c_cyan = CYAN + BOLD
        c_teal = TEAL
        c_star = CYAN + BOLD
        rst = RESET
        return [
            f"        {c_white}▲{rst}     {c_star}✦{rst}",
            f"       {c_white}╱ ╲{rst}   {c_cyan}╭╯{rst}",
            f"     {c_teal}╭{c_white}╱───╲{c_cyan}──╯{rst}",
            f"   {c_teal}❪ {c_white}│  ▲  │{c_teal} ❫{rst}",
            f"    {c_teal}╰{c_white}╲─┬─┬─╱{c_teal}─╮{rst}",
            f"     {c_teal}❪─┼─┼─❫{rst}",
        ]

    # -------------------------------------------------------------------------
    # Compact Identifiers
    # -------------------------------------------------------------------------

    def render_compact_emblem(self) -> str:
        """Render compact single-glyph Aegis emblem."""
        if not self.supports_unicode():
            return self.colorize("[A]", CYAN + BOLD)
        return self.colorize("✦⟨A⟩", CYAN + BOLD)

    def render_assistant_marker(self) -> str:
        """Render conversational assistant turn identity marker."""
        if not self.supports_unicode():
            return f"{self.colorize('[A] ATLAS', BOLD)} {self.colorize('>', CYAN)} "
        return f"{self.colorize('✦ ATLAS', BOLD + CYAN)} {self.colorize('›', CYAN)} "

    def render_completion_badge(self, task_id: str, verified: bool = True) -> str:
        """Render deterministic task completion indicator."""
        if not self.supports_unicode():
            glyph = "[v]" if verified else "[x]"
            return f"  {self.colorize(glyph, GREEN + BOLD)} {self.colorize(f'[AEGIS] Task {task_id} verified', BOLD)}\n"
        glyph = "✦" if verified else "✗"
        return f"  {self.colorize(glyph, CYAN + BOLD)} {self.colorize(f'[AEGIS] Task {task_id} verified', BOLD + GREEN)}\n"

    # -------------------------------------------------------------------------
    # Full Welcome Screen Matching Reference Image
    # -------------------------------------------------------------------------

    def render_welcome_screen(
        self,
        repo_path: str,
        branch: str,
        model: str,
        mode: str = "Local",
        status: str = "Ready",
        session_id: str | None = None,
        width: int | None = None,
    ) -> str:
        """Render full Aegis header and welcome screen matching reference layout."""
        term_width = width or self.get_terminal_width(80)
        emblem_lines = self.get_emblem_lines()
        use_unicode = self.supports_unicode()

        # Wordmark & Pill Badge
        wordmark = self.colorize("ATLAS", WHITE + BOLD)
        pill = self.colorize(f"( v{VERSION} )", CYAN)
        subtitle = self.colorize("AUTONOMOUS DEVELOPMENT ENVIRONMENT", TEAL)

        # Right status badge (e.g. ● Local · Ready)
        dot = self.colorize("●", GREEN + BOLD) if use_unicode else self.colorize("*", GREEN + BOLD)
        mid_dot = self.colorize("·", DIM) if use_unicode else self.colorize("|", DIM)
        status_badge = (
            f"{dot} {self.colorize(mode, WHITE)} {mid_dot} {self.colorize(status, GREEN)}"
        )

        # If terminal width is narrow (< 72), stack vertically
        if term_width < 72:
            lines = [
                "",
                "\n".join(f"  {line}" for line in emblem_lines),
                "",
                f"  {wordmark}   {pill}",
                f"  {subtitle}",
                f"  {status_badge}",
                "",
            ]
        else:
            logo_col_width = 18
            # Calculate right status badge position
            plain_left = f"ATLAS   ( v{VERSION} )"
            plain_status = f"* {mode} | {status}"
            space_available = term_width - logo_col_width - 4
            pad_gap = max(4, space_available - len(plain_left) - len(plain_status))

            title_row_0 = f"{wordmark}   {pill}{' ' * pad_gap}{status_badge}"

            lines = [
                "",
                f"  {pad_visible(emblem_lines[0], logo_col_width)}  ",
                f"  {pad_visible(emblem_lines[1], logo_col_width)}  {title_row_0}",
                f"  {pad_visible(emblem_lines[2], logo_col_width)}  {subtitle}",
                f"  {pad_visible(emblem_lines[3], logo_col_width)}  ",
                f"  {pad_visible(emblem_lines[4], logo_col_width)}  ",
                f"  {pad_visible(emblem_lines[5], logo_col_width)}  ",
            ]

        # Status Bar with Icons
        dir_icon = "📁" if use_unicode else "[DIR]"
        branch_icon = "🔀" if use_unicode else "[BRANCH]"
        model_icon = "⚙" if use_unicode else "[MODEL]"
        pipe = self.colorize("│", DIM) if use_unicode else self.colorize("|", DIM)

        # Truncate repo_path if terminal width requires
        display_path = repo_path
        if len(display_path) > 42 and term_width < 95:
            display_path = "..." + display_path[-39:]

        status_bar = (
            f"  {dir_icon} {self.colorize(display_path, WHITE)}  "
            f"{pipe}  {branch_icon} {self.colorize(branch, CYAN + BOLD)}  "
            f"{pipe}  {model_icon} {self.colorize('Model:', DIM)} {self.colorize(model, WHITE)}"
        )

        divider_len = max(20, min(term_width - 2, 98))
        divider_char = "─" if use_unicode else "-"
        divider = self.colorize(divider_char * divider_len, TEAL)

        # Welcome prompt and commands
        welcome_prompt = self.colorize("What would you like to build today?", WHITE + BOLD)
        commands = [
            "/help",
            "/plan",
            "/test",
            "/review",
            "/status",
            "/approvals",
            "/exit",
        ]
        cmd_str = "   ".join(self.colorize(c, CYAN) for c in commands)
        commands_line = f"{self.colorize('Commands:', WHITE)}  {cmd_str}"

        lines.extend(
            [
                status_bar,
                f" {divider}",
                "",
                f" {welcome_prompt}",
                "",
                f" {commands_line}",
                "",
            ]
        )

        return "\n".join(lines)

    def render_compact_header(
        self,
        repo_path: str,
        branch: str,
        model: str,
        mode: str = "Local",
        session_id: str | None = None,
    ) -> str:
        """Render compact 2-line header with Aegis emblem."""
        use_unicode = self.supports_unicode()
        emblem = self.render_compact_emblem()
        dot = "·" if use_unicode else "|"
        sess_str = f" {dot} {session_id[:12]}" if session_id else ""
        mode_badge = self.colorize(f"[{mode}]", GREEN if mode == "Local" else CYAN)

        line1 = (
            f"{emblem} {self.colorize('ATLAS', WHITE + BOLD)} {self.colorize(f'v{VERSION}', CYAN)}"
        )
        line2 = (
            f"{self.colorize(repo_path, DIM)} {dot} "
            f"{self.colorize(branch, CYAN + BOLD)} {dot} "
            f"{self.colorize(model, YELLOW)} {dot} "
            f"{mode_badge}{self.colorize(sess_str, DIM)}"
        )
        return f"{line1}\n{line2}\n"
