"""Terminal formatters, colors, banners, and table renderers for ATLAS CLI."""

import os
import shutil
import sys
from typing import Any

# ANSI Color Codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
UNDERLINE = "\033[4m"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

BG_DARK = "\033[40m"


def supports_color() -> bool:
    """Check if the current terminal supports ANSI color sequences."""
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def colorize(text: str, color_code: str) -> str:
    """Wrap text in color sequence if colors are supported."""
    return f"{color_code}{text}{RESET}" if supports_color() else text


def render_banner() -> str:
    """Return the official ATLAS CLI ASCII banner."""
    art = f"""{BOLD}{CYAN}
    █████╗ ████████╗██╗      █████╗ ███████╗
   ██╔══██╗╚══██╔══╝██║     ██╔══██╗██╔════╝
   ███████║   ██║   ██║     ███████║███████╗
   ██╔══██║   ██║   ██║     ██╔══██║╚════██║
   ██║  ██║   ██║   ███████╗██║  ██║███████║
   ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚══════╝
{RESET}{DIM}   Autonomous Task & Lifecycle Automation System — v0.16.8{RESET}
"""
    return art if supports_color() else "ATLAS - Autonomous Task & Lifecycle Automation System\n"


def render_badge(text: str, badge_type: str = "primary") -> str:
    """Render a styled badge."""
    color_map = {
        "success": GREEN,
        "warning": YELLOW,
        "danger": RED,
        "primary": CYAN,
        "dim": DIM,
    }
    color = color_map.get(badge_type.lower(), CYAN)
    return colorize(f"[{text.upper()}]", f"{BOLD}{color}")


def render_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Render a clean ASCII/Unicode table formatted with aligned columns and terminal resize awareness."""
    if not headers:
        return ""

    term_width = shutil.get_terminal_size((80, 24)).columns

    str_rows = [[str(cell) for cell in row] for row in rows]
    col_widths = [len(h) for h in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(cell))
            else:
                col_widths.append(len(cell))

    # Pad widths slightly
    col_widths = [w + 2 for w in col_widths]

    # Format header
    header_line = "".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "".join("-" * (w - 1) + " " for w in col_widths)

    out = [colorize(header_line, BOLD), colorize(sep_line, DIM)]
    for row in str_rows:
        line = "".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
        if len(line) > term_width and term_width > 20:
            line = line[: term_width - 3] + "..."
        out.append(line)

    return "\n".join(out)


def render_markdown(text: str) -> str:
    """Simple terminal markdown formatter for headers, bold, and code blocks."""
    lines = text.splitlines()
    formatted = []
    in_code_block = False

    for line in lines:
        if line.startswith("```"):
            in_code_block = not in_code_block
            formatted.append(colorize("----------------------------------------", DIM))
            continue

        if in_code_block:
            formatted.append(colorize(f"  {line}", CYAN))
            continue

        if line.startswith("# "):
            formatted.append(colorize(f"\n=== {line[2:]} ===", f"{BOLD}{CYAN}"))
        elif line.startswith("## "):
            formatted.append(colorize(f"\n--- {line[3:]} ---", f"{BOLD}{WHITE}"))
        elif line.startswith("### "):
            formatted.append(colorize(f"\n* {line[4:]}", f"{BOLD}{YELLOW}"))
        elif line.startswith("- "):
            formatted.append(f"  {colorize('*', CYAN)} {line[2:]}")
        elif "**" in line:
            # Simple bold replacement
            parts = line.split("**")
            res = ""
            for idx, part in enumerate(parts):
                res += colorize(part, BOLD) if idx % 2 == 1 else part
            formatted.append(res)
        else:
            formatted.append(line)

    return "\n".join(formatted)


def render_diff(diff_text: str) -> str:
    """Colorize a unified diff for terminal display."""
    lines = diff_text.splitlines()
    colored = []
    for line in lines:
        if line.startswith("+"):
            colored.append(colorize(line, GREEN))
        elif line.startswith("-"):
            colored.append(colorize(line, RED))
        elif line.startswith("@"):
            colored.append(colorize(line, CYAN))
        else:
            colored.append(line)
    return "\n".join(colored)
