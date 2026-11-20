"""Unit tests for ATLAS Aegis visual identity, branding, and full-screen modern TUI."""

from __future__ import annotations

from atlas_cli.conversation.branding import (
    AegisBranding,
    pad_visible,
    strip_ansi,
)
from atlas_cli.conversation.composer import SlashCompleter


def test_strip_ansi_and_pad_visible() -> None:
    """Verify ANSI escape code stripping and visual width padding."""
    colored_text = "\033[96m\033[1mHELLO\033[0m"
    assert strip_ansi(colored_text) == "HELLO"
    assert len(strip_ansi(colored_text)) == 5

    padded = pad_visible(colored_text, 10)
    assert strip_ansi(padded) == "HELLO     "
    assert len(strip_ansi(padded)) == 10


def test_aegis_unicode_and_color_emblem() -> None:
    """Verify Unicode Aegis emblem with rocket/geometric frame, central A, and compass star."""
    branding = AegisBranding(force_unicode=True, force_color=True)
    lines = branding.get_emblem_lines()

    assert len(lines) == 4
    # Apex & star
    assert "▲" in lines[0]
    assert "✦" in lines[0]
    # Frame & center
    assert "A" in lines[2]


def test_aegis_ascii_fallback_emblem() -> None:
    """Verify graceful ASCII fallback emblem when Unicode is disabled."""
    branding = AegisBranding(force_unicode=False, force_color=False)
    lines = branding.get_emblem_lines()

    assert len(lines) == 4
    assert "^" in lines[0]
    assert "+" in lines[0]
    assert "A" in lines[2]
    for line in lines:
        assert line.isascii(), f"Non-ASCII character found in line: {line}"


def test_compact_emblem_and_header() -> None:
    """Verify single-line compact emblem and 2-line conversation header."""
    b_uni = AegisBranding(force_unicode=True, force_color=True)
    emblem_uni = b_uni.render_compact_emblem()
    assert "✦⟨A⟩" in emblem_uni

    hdr_uni = b_uni.render_compact_header(
        repo_path="/workspace/proj",
        branch="feat/test",
        model="gpt-4o",
        mode="Local",
        session_id="sess_abcdef123456",
    )
    assert "ATLAS" in hdr_uni
    assert "v0.16.8" in hdr_uni
    assert "feat/test" in hdr_uni
    assert "gpt-4o" in hdr_uni
    assert "[Local]" in hdr_uni
    assert "sess_abcdef1" in hdr_uni

    b_asc = AegisBranding(force_unicode=False, force_color=False)
    emblem_asc = b_asc.render_compact_emblem()
    assert emblem_asc == "[A]"

    hdr_asc = b_asc.render_compact_header(
        repo_path="/workspace/proj",
        branch="feat/test",
        model="gpt-4o",
        mode="Local",
        session_id="sess_abcdef123456",
    )
    assert "[A] ATLAS v0.16.8" in hdr_asc
    assert hdr_asc.isascii()


def test_assistant_marker_and_completion_badge() -> None:
    """Verify conversation assistant identity marker and task completion badge."""
    b_uni = AegisBranding(force_unicode=True, force_color=True)
    marker_uni = b_uni.render_assistant_marker()
    assert "✦ ATLAS" in marker_uni
    assert "›" in marker_uni

    badge_uni = b_uni.render_completion_badge("task_42", verified=True)
    assert "✦" in badge_uni
    assert "[AEGIS] Task task_42 verified" in badge_uni

    b_asc = AegisBranding(force_unicode=False, force_color=False)
    marker_asc = b_asc.render_assistant_marker()
    assert "[A] ATLAS >" in marker_asc
    assert marker_asc.isascii()

    badge_asc = b_asc.render_completion_badge("task_42", verified=True)
    assert "[v] [AEGIS] Task task_42 verified" in badge_asc
    assert badge_asc.isascii()


def test_welcome_card_and_execution_tree() -> None:
    """Verify Top Welcome Card and Scrollable Execution Stream tree connectors."""
    branding = AegisBranding(force_unicode=True, force_color=True)

    # 1. Top Welcome Card (Zone 1)
    card = branding.render_welcome_card(
        repo_path="C:/projects/happy-meitner",
        branch="feat/branding",
        model="atlas:hermetic-default",
        mode="Local",
        status="Ready",
        width=96,
    )
    plain_card = strip_ansi(card)
    assert "ATLAS v0.16.8" in plain_card
    assert "Welcome to ATLAS Autonomous Development Environment" in plain_card
    assert "atlas:hermetic-default" in plain_card
    assert "● Ready (Local)" in plain_card
    assert "Tips:" in plain_card
    assert "for commands" in plain_card

    # 2. Execution Stream Tree (Zone 2)
    tree = branding.render_execution_tree(
        task_id="task_6c69b5bb2c31",
        target=r"C:\Users\pc\Documents\antigravity\happy-meitner",
        policy_status="Action Firewall verified",
        next_hint="Type /test to run suites or /review to inspect diffs",
        status="completed",
    )
    plain_tree = strip_ansi(tree)
    assert "Task completed (task_6c69b5bb2c31)" in plain_tree
    assert "Target:  C:\\Users\\pc\\Documents\\antigravity\\happy-meitner" in plain_tree
    assert "Policy:  Action Firewall verified" in plain_tree
    assert "Type /test to run suites or /review to inspect diffs" in plain_tree
    assert "├─" in plain_tree
    assert "└─" in plain_tree


def test_welcome_screen_ascii_and_no_color() -> None:
    """Verify welcome screen in strict ASCII, uncolored environment."""
    branding = AegisBranding(force_unicode=False, force_color=False)
    screen = branding.render_welcome_card(
        repo_path="C:/workspace",
        branch="main",
        model="local-model",
        mode="Local",
        status="Ready",
        width=80,
    )
    assert screen.isascii()
    assert "* Ready (Local)" in screen
    assert "\033[" not in screen  # Zero ANSI escape sequences


def test_slash_completer_and_status_footer() -> None:
    """Verify SlashCompleter popup commands and 2-line persistent footer."""
    completer = SlashCompleter()
    from prompt_toolkit.document import Document

    completions = list(completer.get_completions(Document("/"), None))
    cmds = [c.text for c in completions]
    assert "/help" in cmds
    assert "/plan" in cmds
    assert "/test" in cmds
    assert "/review" in cmds
    assert "/status" in cmds
    assert "/approvals" in cmds
    assert "/exit" in cmds

    branding = AegisBranding(force_unicode=True, force_color=True)
    footer = branding.render_status_footer(
        repo_name="happy-meitner",
        branch="feat/tui",
        model="atlas:hermetic-default",
    )
    plain_footer = strip_ansi(footer)
    assert "happy-meitner" in plain_footer
    assert "feat/tui" in plain_footer
    assert "shortcuts" in plain_footer
    assert "Ctrl+C exit" in plain_footer


def test_environment_variable_overrides(monkeypatch) -> None:
    """Verify ATLAS_NO_UNICODE and NO_COLOR environment flags."""
    monkeypatch.setenv("ATLAS_NO_UNICODE", "1")
    monkeypatch.setenv("NO_COLOR", "1")

    branding = AegisBranding()
    assert branding.supports_unicode() is False
    assert branding.supports_color() is False

    emblem = branding.render_compact_emblem()
    assert emblem == "[A]"
    assert "\033[" not in emblem
