"""ATLAS Aegis Visual Identity, Palette, and Full-Screen Modern TUI Components.

Implements the modern full-screen TUI inspired by Claude Code and OpenCode:
- TrueColor dual-accent palette (#38BDF8 Sky Cyan, #F97316 Warm Coral, #22C55E Emerald)
- Top Welcome Card (rounded box, max-width 96, rocket/Aegis emblem, status)
- Execution stream tree connectors (│, ├─, └─ in #334155)
- Anchored input box and persistent status footer
"""

from __future__ import annotations

import os
import re
import shutil
import sys

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

VERSION = "0.17.0"

# -----------------------------------------------------------------------------
# 1. Color Palette (TrueColor / Hex)
# -----------------------------------------------------------------------------
COLOR_BG = "#0D1117"  # Deep terminal dark
COLOR_PRIMARY = "#38BDF8"  # Sky Cyan (Logo, active borders, slash commands)
COLOR_SECONDARY = "#F97316"  # Warm Coral/Amber (Active input border focus, running states)
COLOR_SUCCESS = "#22C55E"  # Emerald Green (Ready, completed tasks)
COLOR_TEXT_PRIMARY = "#F1F5F9"  # Crisp Off-White
COLOR_TEXT_MUTED = "#64748B"  # Slate Gray (Tree connectors, hints, secondary labels)
COLOR_TEXT_SLATE = "#94A3B8"  # Slate 400 (Tips, descriptions)
COLOR_BORDER = "#334155"  # Dark Slate (Inactive container borders and dividers)

# ANSI TrueColor Sequences
ANSI_PRIMARY = "\033[38;2;56;189;248m"
ANSI_SECONDARY = "\033[38;2;249;115;22m"
ANSI_SUCCESS = "\033[38;2;34;197;94m"
ANSI_WHITE = "\033[38;2;241;245;249m"
ANSI_MUTED = "\033[38;2;100;116;139m"
ANSI_SLATE = "\033[38;2;148;163;184m"
ANSI_BORDER = "\033[38;2;51;65;85m"
BOLD = "\033[1m"
DIM = "\033[90m"
RESET = "\033[0m"

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
    """Reusable presentation component for ATLAS modern TUI visual identity."""

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
        encoding = getattr(sys.stdout, "encoding", "") or ""
        if encoding.lower() in ("utf-8", "utf8", "utf_8"):
            return True
        if sys.platform == "win32":
            if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"):
                return True
        return False

    def supports_color(self) -> bool:
        """Check whether terminal environment supports ANSI TrueColor sequences."""
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
        """Retrieve current terminal width capped at max 96 columns."""
        try:
            cols = shutil.get_terminal_size((default, 24)).columns
            return min(cols, 96)
        except Exception:
            return min(default, 96)

    # -------------------------------------------------------------------------
    # Emblem Geometry
    # -------------------------------------------------------------------------

    def get_emblem_lines(self) -> list[str]:
        """Return 4-line compact geometric/rocket ASCII emblem."""
        use_unicode = self.supports_unicode()
        use_color = self.supports_color()

        if not use_unicode:
            if not use_color:
                return [
                    "    ^ +  ",
                    "   /|\\ \\ ",
                    "  | A |  ",
                    "   \\=/   ",
                ]
            c_pri = ANSI_PRIMARY + BOLD
            rst = RESET
            return [
                f"    {c_pri}^{rst} {c_pri}+{rst}  ",
                f"   {c_pri}/|\\ \\{rst} ",
                f"  {c_pri}| A |{rst}  ",
                f"   {c_pri}\\=/{rst}   ",
            ]

        if not use_color:
            return [
                "    ▲ ✦  ",
                "   / █ \\ ",
                "  | ⟨A⟩ |",
                "   \\═══/ ",
            ]

        c_pri = ANSI_PRIMARY + BOLD
        rst = RESET
        return [
            f"    {c_pri}▲{rst} {c_pri}✦{rst}  ",
            f"   {c_pri}/ █ \\{rst} ",
            f"  {c_pri}| ⟨A⟩ |{rst}",
            f"   {c_pri}\\═══/{rst} ",
        ]

    # -------------------------------------------------------------------------
    # Zone 1: Top Welcome Card (Rounded Box in #334155, Max-Width 96)
    # -------------------------------------------------------------------------

    def render_welcome_card(
        self,
        repo_path: str,
        branch: str,
        model: str = "openrouter/free",
        mode: str = "Local",
        status: str = "Ready",
        width: int | None = None,
    ) -> str:
        """Render Top Welcome Card adhering to Section 2.1."""
        target_width = min(width or self.get_terminal_width(96), 96)
        use_unicode = self.supports_unicode()
        use_color = self.supports_color()

        if not use_color:
            return self._render_welcome_card_plain(
                repo_path=repo_path,
                branch=branch,
                model=model,
                mode=mode,
                status=status,
                width=target_width,
                use_unicode=use_unicode,
            )

        # Rich formatted card
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left", width=12)
        table.add_column(justify="left")

        emblem = Text()
        if use_unicode:
            emblem.append("    ▲ ✦\n", style=f"bold {COLOR_PRIMARY}")
            emblem.append("   / █ \\\n", style=f"bold {COLOR_PRIMARY}")
            emblem.append("  | ⟨A⟩ |\n", style=f"bold {COLOR_PRIMARY}")
            emblem.append("   \\═══/", style=f"bold {COLOR_PRIMARY}")
        else:
            emblem.append("    ^ +\n", style=f"bold {COLOR_PRIMARY}")
            emblem.append("   /|\\ \\\n", style=f"bold {COLOR_PRIMARY}")
            emblem.append("  | A |\n", style=f"bold {COLOR_PRIMARY}")
            emblem.append("   \\=/", style=f"bold {COLOR_PRIMARY}")

        right = Text()
        right.append(
            "Welcome to ATLAS Autonomous Development Environment\n",
            style=f"bold {COLOR_TEXT_PRIMARY}",
        )
        right.append("Model: ", style=COLOR_TEXT_MUTED)
        right.append(model, style=COLOR_TEXT_PRIMARY)
        right.append("  •  ", style=COLOR_TEXT_MUTED)
        right.append("Status: ", style=COLOR_TEXT_MUTED)
        right.append(f"● {status} ({mode})\n", style=COLOR_SUCCESS)
        right.append("Tips: ", style=COLOR_TEXT_MUTED)
        right.append("Describe a feature to build, or type ", style=COLOR_TEXT_SLATE)
        right.append("/", style=f"bold {COLOR_PRIMARY}")
        right.append(" for commands", style=COLOR_TEXT_SLATE)

        table.add_row(emblem, right)

        panel = Panel(
            table,
            title=f"[bold {COLOR_PRIMARY}]ATLAS v{VERSION}[/]",
            title_align="left",
            border_style=COLOR_BORDER,
            box=box.ROUNDED if use_unicode else box.ASCII,
            safe_box=False if use_unicode else True,
            width=target_width,
            padding=(0, 1),
        )

        console = Console(width=target_width, record=True, color_system="truecolor")
        with console.capture() as capture:
            console.print(panel)
        return capture.get()

    def _render_welcome_card_plain(
        self,
        repo_path: str,
        branch: str,
        model: str,
        mode: str,
        status: str,
        width: int,
        use_unicode: bool,
    ) -> str:
        """Render plain text / ASCII card without ANSI colors."""
        tl = "╭" if use_unicode else "+"
        tr = "╮" if use_unicode else "+"
        bl = "╰" if use_unicode else "+"
        br = "╯" if use_unicode else "+"
        h = "─" if use_unicode else "-"
        v = "│" if use_unicode else "|"
        mid_dot = "•" if use_unicode else "*"

        title = f" ATLAS v{VERSION} "
        fill = max(0, width - 2 - len(title))
        top = f"{tl}{title}{h * fill}{tr}"
        bot = f"{bl}{h * (width - 2)}{br}"

        emblem = [
            "    ▲ ✦  " if use_unicode else "    ^ +  ",
            "   / █ \\ " if use_unicode else "   /|\\ \\ ",
            "  | ⟨A⟩ |" if use_unicode else "  | A |  ",
            "   \\═══/ " if use_unicode else "   \\=/   ",
        ]
        stat_bullet = "●" if use_unicode else "*"
        right = [
            "Welcome to ATLAS Autonomous Development Environment",
            f"Model: {model}  {mid_dot}  Status: {stat_bullet} {status} ({mode})",
            "Tips: Describe a feature to build, or type / for commands",
            "",
        ]

        lines = [top]
        for e, r in zip(emblem, right, strict=False):
            inner = f"{e}  {r}"
            pad = max(0, width - 4 - len(inner))
            lines.append(f"{v} {inner}{' ' * pad} {v}")
        lines.append(bot)
        return "\n".join(lines) + "\n"

    # Backward compatibility alias
    def render_welcome_screen(
        self,
        repo_path: str,
        branch: str,
        model: str = "openrouter/free",
        mode: str = "Local",
        status: str = "Ready",
        session_id: str | None = None,
        width: int | None = None,
    ) -> str:
        return self.render_welcome_card(
            repo_path=repo_path,
            branch=branch,
            model=model,
            mode=mode,
            status=status,
            width=width,
        )

    # -------------------------------------------------------------------------
    # Zone 2: Scrollable Execution Stream & Tree Connectors
    # -------------------------------------------------------------------------

    def render_execution_tree(
        self,
        task_id: str,
        target: str,
        policy_status: str = "Action Firewall verified",
        next_hint: str = "Type /test to run suites or /review to inspect diffs",
        status: str = "completed",
    ) -> str:
        """Render execution summary using clean tree connectors adhering to Section 2.2."""
        use_unicode = self.supports_unicode()
        use_color = self.supports_color()

        pipe = "│" if use_unicode else "|"
        tee = "├─" if use_unicode else "|-"
        ell = "└─" if use_unicode else "\\-"
        dot = "●" if use_unicode else "*"

        if not use_color:
            return (
                f"\n  {dot} Task {status} ({task_id})\n"
                f"  {pipe}\n"
                f"  {tee} Target:  {target}\n"
                f"  {tee} Policy:  {policy_status}\n"
                f"  {ell} Next:    {next_hint}\n"
            )

        dot_color = COLOR_SUCCESS if status == "completed" else COLOR_SECONDARY

        text = Text()
        text.append("\n  ● ", style=f"bold {dot_color}")
        text.append(f"Task {status} ", style=f"bold {COLOR_TEXT_PRIMARY}")
        text.append(f"({task_id})\n", style=COLOR_TEXT_MUTED)

        text.append(f"  {pipe}\n", style=COLOR_BORDER)
        text.append(f"  {tee} ", style=COLOR_BORDER)
        text.append("Target:  ", style=COLOR_TEXT_MUTED)
        text.append(f"{target}\n", style=COLOR_TEXT_PRIMARY)

        text.append(f"  {tee} ", style=COLOR_BORDER)
        text.append("Policy:  ", style=COLOR_TEXT_MUTED)
        text.append(f"{policy_status}\n", style=COLOR_SUCCESS)

        text.append(f"  {ell} ", style=COLOR_BORDER)
        text.append("Next:    ", style=COLOR_TEXT_MUTED)

        # Highlight slash commands in #38BDF8
        parts = re.split(r"(/test|/review|/plan|/status|/approvals|/help|/exit)", next_hint)
        for p in parts:
            if p.startswith("/"):
                text.append(p, style=f"bold {COLOR_PRIMARY}")
            else:
                text.append(p, style=COLOR_TEXT_SLATE)
        text.append("\n")

        console = Console(width=96, record=True, color_system="truecolor")
        with console.capture() as capture:
            console.print(text)
        return capture.get()

    # -------------------------------------------------------------------------
    # Zone 3: Anchored Bottom Input Box & Persistent Status Footer
    # -------------------------------------------------------------------------

    def render_status_footer(
        self,
        repo_name: str,
        branch: str,
        model: str = "openrouter/free",
        width: int = 96,
    ) -> str:
        """Render 2-line persistent status footer adhering to Section 2.3."""
        use_unicode = self.supports_unicode()
        use_color = self.supports_color()

        dir_icon = "📁" if use_unicode else "[DIR]"
        branch_icon = "🔀" if use_unicode else "[BRANCH]"
        model_icon = "⚙" if use_unicode else "[MODEL]"
        pipe = "│" if use_unicode else "|"
        dot = "•" if use_unicode else "*"

        line1 = (
            f" {dir_icon} {repo_name}  {pipe}  {branch_icon} {branch}  {pipe}  {model_icon} {model}"
        )
        line2 = f"? shortcuts  {dot}  / commands  {dot}  Esc cancel  {dot}  Ctrl+C exit"

        if not use_color:
            return f"\n{line1}\n{line2}\n"

        return f"\n{self.colorize(line1, ANSI_MUTED)}\n{self.colorize(line2, ANSI_MUTED)}\n"

    def render_input_border(self, active: bool = True, width: int = 96) -> tuple[str, str]:
        """Generate top and bottom borders for the rounded input container."""
        use_unicode = self.supports_unicode()
        tl = "╭" if use_unicode else "+"
        tr = "╮" if use_unicode else "+"
        bl = "╰" if use_unicode else "+"
        br = "╯" if use_unicode else "+"
        h = "─" if use_unicode else "-"

        target_width = min(width, 96)
        color = ANSI_SECONDARY if active else ANSI_BORDER

        top = self.colorize(f"{tl}{h * (target_width - 2)}{tr}", color)
        bot = self.colorize(f"{bl}{h * (target_width - 2)}{br}", color)
        return top, bot

    # -------------------------------------------------------------------------
    # Compact Identifiers
    # -------------------------------------------------------------------------

    def render_compact_emblem(self) -> str:
        """Render compact single-glyph Aegis emblem."""
        if not self.supports_unicode():
            return self.colorize("[A]", ANSI_PRIMARY + BOLD)
        return self.colorize("✦⟨A⟩", ANSI_PRIMARY + BOLD)

    def render_assistant_marker(self) -> str:
        """Render conversational assistant turn identity marker."""
        if not self.supports_unicode():
            return f"{self.colorize('[A] ATLAS', BOLD)} {self.colorize('>', ANSI_PRIMARY)} "
        return (
            f"{self.colorize('✦ ATLAS', BOLD + ANSI_PRIMARY)} {self.colorize('›', ANSI_PRIMARY)} "
        )

    def render_completion_badge(self, task_id: str, verified: bool = True) -> str:
        """Render deterministic task completion indicator."""
        if not self.supports_unicode():
            glyph = "[v]" if verified else "[x]"
            return f"  {self.colorize(glyph, ANSI_SUCCESS + BOLD)} {self.colorize(f'[AEGIS] Task {task_id} verified', BOLD)}\n"
        glyph = "✦" if verified else "✗"
        return f"  {self.colorize(glyph, ANSI_PRIMARY + BOLD)} {self.colorize(f'[AEGIS] Task {task_id} verified', BOLD + ANSI_SUCCESS)}\n"

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
        mode_badge = self.colorize(f"[{mode}]", ANSI_SUCCESS if mode == "Local" else ANSI_PRIMARY)
        aegis_tag = self.colorize("[AEGIS]", ANSI_MUTED + BOLD)

        line1 = f"{aegis_tag} {emblem} {self.colorize('ATLAS', ANSI_WHITE + BOLD)} {self.colorize(f'v{VERSION}', ANSI_PRIMARY)}"
        line2 = (
            f"{self.colorize(repo_path, ANSI_MUTED)} {dot} "
            f"{self.colorize(branch, ANSI_PRIMARY + BOLD)} {dot} "
            f"{self.colorize(model, ANSI_SLATE)} {dot} "
            f"{mode_badge}{self.colorize(sess_str, ANSI_MUTED)}"
        )
        return f"{line1}\n{line2}\n"
