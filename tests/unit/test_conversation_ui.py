"""Comprehensive unit and integration test suite for ATLAS Conversation-First UI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from atlas_cli.conversation.app import ConversationApp
from atlas_cli.conversation.composer import (
    PromptComposer,
    SlashCommandDispatcher,
)
from atlas_cli.conversation.header import ConversationHeader
from atlas_cli.conversation.inspector import AdvancedInspector
from atlas_cli.conversation.renderer import (
    ConversationRenderer,
    highlight_code_block,
    render_markdown,
    stream_markdown,
)
from atlas_cli.main import main

# ============================================================================
# 1. Header and Welcome Presentation Tests
# ============================================================================


def test_conversation_header_and_welcome(tmp_path: Path) -> None:
    """Verify compact header and welcome screen rendering."""
    header = ConversationHeader(repo_root=tmp_path)

    # 1. Branch detection
    branch = header.get_git_branch()
    assert isinstance(branch, str)

    # 2. Model identifier
    model_id = header.get_model_identifier()
    assert (
        "atlas" in model_id.lower()
        or "default" in model_id.lower()
        or "free" in model_id.lower()
        or "openrouter" in model_id.lower()
    )

    # 3. Execution mode
    mode = header.get_execution_mode()
    assert mode in ("Local", "Remote Control Plane")

    # 4. Header rendering
    rendered_hdr = header.render_header(session_id="sess_1234567890")
    assert "ATLAS v0.16.8" in rendered_hdr
    assert str(tmp_path) in rendered_hdr
    assert branch in rendered_hdr
    assert "sess_1234567" in rendered_hdr

    # 5. Welcome rendering
    welcome = header.render_welcome()
    assert "ATLAS" in welcome
    assert (
        "Autonomous Development Environment" in welcome
        or "AUTONOMOUS DEVELOPMENT ENVIRONMENT" in welcome.upper()
    )
    assert "Model:" in welcome
    assert "Status:" in welcome


# ============================================================================
# 2. Rendering, Streaming, and Activity Tests
# ============================================================================


def test_renderer_activity_indicators_and_file_summaries() -> None:
    """Verify tool activity badges, inline file changes, and prompt rendering."""
    renderer = ConversationRenderer()

    # User prompt
    user_line = renderer.render_user_prompt("Build REST API endpoints")
    assert "›" in user_line
    assert "Build REST API endpoints" in user_line

    # Activity: Running
    act_run = renderer.render_activity(
        "Exploring repository files", detail="40 files", status="RUNNING"
    )
    assert "•" in act_run
    assert "Exploring repository files" in act_run
    assert "40 files" in act_run

    # Activity: Success with duration
    act_ok = renderer.render_activity(
        "Running test suite", detail="22 passed", status="SUCCESS", duration_ms=450.0
    )
    assert "✓" in act_ok
    assert "Running test suite" in act_ok
    assert "[0.45s]" in act_ok

    # Activity: Failed
    act_fail = renderer.render_activity("Syntax check", detail="Error on line 12", status="FAILED")
    assert "✗" in act_fail
    assert "Syntax check" in act_fail

    # Inline file changes
    class MockChange:
        def __init__(self, path: str, change_type: str, added: int, removed: int):
            self.path = path
            self.change_type = change_type
            self.lines_added = added
            self.lines_removed = removed

    changes = [
        MockChange("apps/api/routes/auth.py", "CREATE", 84, 0),
        MockChange("apps/api/main.py", "MODIFY", 12, 3),
        MockChange("legacy_auth.py", "DELETE", 0, 50),
    ]
    summary = renderer.render_file_changes(changes)
    assert "Files modified (3):" in summary
    assert "+" in summary
    assert "~" in summary
    assert "-" in summary
    assert "apps/api/routes/auth.py" in summary
    assert "(+84 / -0)" in summary


def test_markdown_and_syntax_highlighting() -> None:
    """Verify markdown syntax highlighting and formatting."""
    md_text = (
        "# Header 1\n"
        "## Header 2\n"
        "**Important bold statement** and `config_param`.\n"
        "- List item A\n"
        "```python\n"
        "def compute(x: int) -> int:\n"
        "    return x * 2\n"
        "```\n"
    )
    rendered = render_markdown(md_text)
    assert "Header 1" in rendered
    assert "Header 2" in rendered
    assert "Important bold statement" in rendered
    assert "config_param" in rendered
    assert "•" in rendered

    # Code block highlight
    code = "x = 42\nprint(x)\n"
    highlighted = highlight_code_block(code, "python")
    assert "x" in highlighted
    assert "42" in highlighted


def test_stream_markdown_output(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify smooth streaming output."""
    sample = "ATLAS autonomous engine verified all steps."
    stream_markdown(sample, delay=0.001)
    captured = capsys.readouterr().out
    assert "ATLAS" in captured
    assert "autonomous" in captured
    assert "verified" in captured


# ============================================================================
# 3. Contextual Approval Experience & Action Firewall Tests
# ============================================================================


def test_approval_card_rendering_and_interaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify approval prompt card, grant, deny, and cancel behaviors."""
    renderer = ConversationRenderer()
    approval_req = {
        "request_id": "req_audit_001",
        "action": "Run terminal command",
        "target": "Current workspace",
        "parameters": {"command": "pytest -v"},
        "risk_level": "CRITICAL",
    }
    card = renderer.render_approval_card(approval_req)
    assert "ATLAS wants permission to execute:" in card
    assert "Run terminal command" in card
    assert "pytest -v" in card
    assert "CRITICAL" in card
    assert "[A] Approve" in card
    assert "[D] Deny" in card

    # Test grant approval interaction in app
    app = ConversationApp(repo_root=tmp_path)
    app.client.list_approvals = MagicMock(return_value=[approval_req])  # type: ignore[method-assign]
    app.client.grant_approval = MagicMock(return_value={"status": "APPROVED"})  # type: ignore[method-assign]

    monkeypatch.setattr("builtins.input", lambda _: "a")
    res_grant = app.handle_pending_approvals()
    assert res_grant is True
    app.client.grant_approval.assert_called_once_with("req_audit_001")

    # Test deny approval interaction in app
    app.client.deny_approval = MagicMock(return_value={"status": "DENIED"})  # type: ignore[method-assign]
    monkeypatch.setattr("builtins.input", lambda _: "d")
    res_deny = app.handle_pending_approvals()
    assert res_deny is False
    app.client.deny_approval.assert_called_once_with("req_audit_001")


# ============================================================================
# 4. Prompt Composer & Multiline Tests
# ============================================================================


def test_prompt_composer_single_and_multiline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify prompt composer with single-line, multiline '\\', and history."""
    composer = PromptComposer()

    # 1. Single line prompt
    monkeypatch.setattr("builtins.input", lambda _: "Implement payment gateway")
    p1 = composer.prompt()
    assert p1 == "Implement payment gateway"
    assert composer.history == ["Implement payment gateway"]

    # 2. Multiline prompt with trailing '\'
    inputs = iter(["First line of prompt \\", "Second line of prompt \\", "Third line", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    p2 = composer.prompt()
    assert "First line of prompt" in p2
    assert "Second line of prompt" in p2
    assert "Third line" in p2

    # 3. Slash command detection
    assert PromptComposer.is_slash_command("/help") is True
    assert PromptComposer.is_slash_command("/plan build api") is True
    assert PromptComposer.is_slash_command("Build API endpoint") is False

    # 4. Command help palette
    help_palette = PromptComposer.get_command_help()
    assert "/help" in help_palette
    assert "/status" in help_palette
    assert "/plan" in help_palette
    assert "/test" in help_palette
    assert "/review" in help_palette
    assert "/approvals" in help_palette
    assert "/agents" in help_palette
    assert "/inspector" in help_palette


# ============================================================================
# 5. Slash Command Dispatcher Tests
# ============================================================================


def test_slash_command_dispatcher(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify routing of all required slash commands to CLI services."""
    app = ConversationApp(repo_root=tmp_path)
    dispatcher = SlashCommandDispatcher(app=app, repo_root=str(tmp_path))

    # /help
    assert dispatcher.dispatch("/help") is True
    assert "AVAILABLE SLASH COMMANDS" in capsys.readouterr().out

    # /status
    assert dispatcher.dispatch("/status") is True
    assert "PLATFORM STATUS" in capsys.readouterr().out

    # /model & /models
    assert dispatcher.dispatch("/model") is True
    out_models = capsys.readouterr().out
    assert "MODEL" in out_models or "provider" in out_models.lower()

    # /plan
    assert dispatcher.dispatch("/plan Refactor logging subsystem") is True
    assert "ATLAS PLANNER" in capsys.readouterr().out

    # /permissions
    assert dispatcher.dispatch("/permissions") is True
    assert "ACTION FIREWALL" in capsys.readouterr().out

    # /agents
    assert dispatcher.dispatch("/agents") is True
    assert "AUTONOMOUS SPECIALIST AGENTS" in capsys.readouterr().out

    # /sessions
    assert dispatcher.dispatch("/sessions") is True
    assert "SESSIONS" in capsys.readouterr().out

    # /compact
    assert dispatcher.dispatch("/compact") is True
    capsys.readouterr()

    # Unknown command handling
    assert dispatcher.dispatch("/unknown-command-xyz") is True
    out_err = capsys.readouterr().out
    assert "Unknown command" in out_err
    assert "/unknown-command-xyz" in out_err

    # /exit and /quit return False to terminate loop
    assert dispatcher.dispatch("/exit") is False
    assert dispatcher.dispatch("/quit") is False


# ============================================================================
# 6. Advanced Diagnostic Inspector Tests
# ============================================================================


def test_advanced_inspector_panels(tmp_path: Path) -> None:
    """Verify on-demand diagnostic inspector renders all 8 panels."""
    inspector = AdvancedInspector(repo_root=str(tmp_path))

    # Header with tabs
    hdr = inspector.render_panel_header()
    assert "1. Conversation" in hdr
    assert "2. Agent Activity" in hdr
    assert "3. Task Graph" in hdr
    assert "4. Terminal" in hdr
    assert "5. File Changes" in hdr
    assert "6. Approvals" in hdr
    assert "7. Timeline" in hdr
    assert "8. Runtime" in hdr

    # Panel 0: Conversation
    inspector.active_panel_idx = 0
    p0 = inspector.render_content()
    assert "No conversation" in p0 or "Conversation" in p0

    # Panel 1: Agent Activity
    inspector.active_panel_idx = 1
    p1 = inspector.render_content()
    assert "agent" in p1.lower() or "status" in p1.lower()

    # Panel 2: Task Graph
    inspector.active_panel_idx = 2
    p2 = inspector.render_content()
    assert "Task DAG" in p2

    # Panel 4: File Changes
    inspector.active_panel_idx = 4
    p4 = inspector.render_content()
    assert "clean" in p4.lower() or "diff" in p4.lower()

    # Panel 5: Approvals
    inspector.active_panel_idx = 5
    p5 = inspector.render_content()
    assert "approvals" in p5.lower()

    # Panel 7: Runtime
    inspector.active_panel_idx = 7
    p7 = inspector.render_content()
    assert "Server Health" in p7


# ============================================================================
# 7. Conversational Turn Execution & Invariant Tests
# ============================================================================


def test_conversation_app_turn_execution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify execute_turn performs planning, verification, and session persistence."""
    from atlas_core.contracts.model import ModelResponse, TokenUsage

    app = ConversationApp(repo_root=tmp_path)

    # Inject mock router for deterministic hermetic unit testing
    mock_router = MagicMock()
    mock_router.default_free_model = "openrouter/free"
    mock_response = ModelResponse(
        response_id="resp_test_123",
        request_id="conv_test_123",
        model_name="openrouter/free",
        content="Here is the auth module unit test suite.",
        latency_ms=350,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )
    mock_router.complete = AsyncMock(return_value=mock_response)
    app._model_router = mock_router

    # Execute a turn
    app.execute_turn("Build unit test suite for auth module")
    out = capsys.readouterr().out

    # Check that turn activity badges and response content were emitted
    assert "Requesting free model" in out
    assert "Free model responded" in out
    assert "openrouter/free" in out
    assert "Here is the auth module unit test suite." in out

    # Verify session persisted in SessionManager
    saved = app.sess_mgr.get_session(app.session["session_id"])
    assert saved is not None
    assert len(saved.get("messages", [])) >= 2
    assert saved["messages"][0]["content"] == "Build unit test suite for auth module"
    assert "Here is the auth module unit test suite." in saved["messages"][1]["content"]


# ============================================================================
# 8. Main CLI Router Launches Conversation App
# ============================================================================


def test_cli_main_launches_conversation_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify launching atlas with no args or --tui launches conversation-first UI."""
    called = []

    def mock_run_conversation_app(*args, **kwargs):
        called.append("conversation_app")
        return 0

    monkeypatch.setattr("atlas_cli.main.run_conversation_app", mock_run_conversation_app)

    # 1. atlas --tui
    res_tui = main(["--tui"])
    assert res_tui == 0
    assert "conversation_app" in called

    # 2. atlas with mock TTY
    called.clear()
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    res_default = main([])
    assert res_default == 0
    assert "conversation_app" in called
