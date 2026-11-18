"""Unit tests for ATLAS Aegis visual identity, branding, and terminal fallbacks."""

from __future__ import annotations

from atlas_cli.conversation.branding import (
    AegisBranding,
    pad_visible,
    strip_ansi,
)


def test_strip_ansi_and_pad_visible() -> None:
    """Verify ANSI escape code stripping and visual width padding."""
    colored_text = "\033[96m\033[1mHELLO\033[0m"
    assert strip_ansi(colored_text) == "HELLO"
    assert len(strip_ansi(colored_text)) == 5

    padded = pad_visible(colored_text, 10)
    assert strip_ansi(padded) == "HELLO     "
    assert len(strip_ansi(padded)) == 10


def test_aegis_unicode_and_color_emblem() -> None:
    """Verify Unicode Aegis emblem with orbital ring, central A, and compass star."""
    branding = AegisBranding(force_unicode=True, force_color=True)
    lines = branding.get_emblem_lines()

    assert len(lines) == 6
    # Apex & star
    assert "▲" in lines[0]
    assert "✦" in lines[0]
    # Orbital ring & center
    assert "╭" in lines[2]
    assert "▲" in lines[3]
    assert "╰" in lines[4]


def test_aegis_ascii_fallback_emblem() -> None:
    """Verify graceful ASCII fallback emblem when Unicode is disabled."""
    branding = AegisBranding(force_unicode=False, force_color=False)
    lines = branding.get_emblem_lines()

    assert len(lines) == 6
    # ASCII characters only
    assert "^" in lines[0]
    assert "+" in lines[0]
    assert "/ \\" in lines[1]
    assert "+" in lines[2]
    assert "|" in lines[3]
    # Ensure zero non-ASCII characters exist in any line
    for line in lines:
        assert line.isascii(), f"Non-ASCII character found in line: {line}"


def test_compact_emblem_and_header() -> None:
    """Verify single-line compact emblem and 2-line conversation header."""
    # Unicode mode
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

    # ASCII fallback mode
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
    # Unicode mode
    b_uni = AegisBranding(force_unicode=True, force_color=True)
    marker_uni = b_uni.render_assistant_marker()
    assert "✦ ATLAS" in marker_uni
    assert "›" in marker_uni

    badge_uni = b_uni.render_completion_badge("task_42", verified=True)
    assert "✦" in badge_uni
    assert "[AEGIS] Task task_42 verified" in badge_uni

    # ASCII fallback mode
    b_asc = AegisBranding(force_unicode=False, force_color=False)
    marker_asc = b_asc.render_assistant_marker()
    assert "[A] ATLAS >" in marker_asc
    assert marker_asc.isascii()

    badge_asc = b_asc.render_completion_badge("task_42", verified=True)
    assert "[v] [AEGIS] Task task_42 verified" in badge_asc
    assert badge_asc.isascii()


def test_welcome_screen_wide_and_narrow_layout() -> None:
    """Verify responsive layout across wide (>=72) and narrow (<72) terminals."""
    branding = AegisBranding(force_unicode=True, force_color=True)

    # Wide layout (100 columns)
    wide_screen = branding.render_welcome_screen(
        repo_path="C:/projects/happy-meitner",
        branch="feat/branding",
        model="atlas-hermetic-default",
        mode="Local",
        status="Ready",
        width=100,
    )
    plain_wide = strip_ansi(wide_screen)
    assert "ATLAS" in plain_wide
    assert "( v0.16.8 )" in plain_wide
    assert "AUTONOMOUS DEVELOPMENT ENVIRONMENT" in plain_wide
    assert "● Local · Ready" in plain_wide
    assert "📁 C:/projects/happy-meitner" in plain_wide
    assert "🔀 feat/branding" in plain_wide
    assert "What would you like to build today?" in plain_wide
    assert "/help" in plain_wide
    assert "/plan" in plain_wide

    # Narrow layout (60 columns - stacks vertically)
    narrow_screen = branding.render_welcome_screen(
        repo_path="C:/projects/happy-meitner",
        branch="feat/branding",
        model="atlas-hermetic-default",
        mode="Local",
        status="Ready",
        width=60,
    )
    plain_narrow = strip_ansi(narrow_screen)
    assert "ATLAS" in plain_narrow
    assert "( v0.16.8 )" in plain_narrow
    assert "AUTONOMOUS DEVELOPMENT ENVIRONMENT" in plain_narrow


def test_welcome_screen_ascii_and_no_color() -> None:
    """Verify welcome screen in strict ASCII, uncolored environment."""
    branding = AegisBranding(force_unicode=False, force_color=False)
    screen = branding.render_welcome_screen(
        repo_path="C:/workspace",
        branch="main",
        model="local-model",
        mode="Local",
        status="Ready",
        width=80,
    )
    assert screen.isascii()
    assert "[DIR]" in screen
    assert "[BRANCH]" in screen
    assert "[MODEL]" in screen
    assert "* Local | Ready" in screen
    assert "\033[" not in screen  # Zero ANSI escape sequences


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
