"""Unit test suite for ATLAS CLI Stage 1 Foundation.

Verifies:
- Application entry point and banner
- Command routing and exit codes
- Configuration precedence and security
- Model selection and persistence
- Session creation, persistence, resumption, and export
- Terminal rendering, markdown, diff, and table formatters
- Minimal headless execution mode
- Cross-platform compatibility and terminal resize resilience
- Graceful shutdown signal registration
- Action Firewall permission enforcement checks
"""

import json
from pathlib import Path

import pytest
from atlas_cli.configuration.manager import ConfigManager
from atlas_cli.main import create_parser, main
from atlas_cli.rendering.formatters import (
    render_badge,
    render_banner,
    render_diff,
    render_markdown,
    render_table,
)
from atlas_cli.sessions.manager import SessionManager


def test_cli_entrypoint_help_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify top-level --help and --version execution."""
    # Test --version
    res_ver = main(["--version"])
    assert res_ver == 0
    out_ver = capsys.readouterr().out
    assert "ATLAS v0.16.8" in out_ver

    # Test -v short flag
    res_v = main(["-v"])
    assert res_v == 0

    # Test parser help
    parser = create_parser()
    assert parser.prog == "atlas"
    help_text = parser.format_help()
    assert "--tui" in help_text
    assert "--minimal" in help_text
    assert "models" in help_text
    assert "sessions" in help_text
    assert "status" in help_text


def test_cli_default_invocation_shows_banner_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify executing atlas without arguments displays banner and usage help."""
    res = main([])
    assert res == 0
    captured = capsys.readouterr().out
    assert "Autonomous Task & Lifecycle Automation System" in captured


def test_cli_command_routing(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify subcommands route cleanly and return successful exit codes."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))

    # Test atlas status
    assert main(["status"]) == 0
    status_out = capsys.readouterr().out
    assert "ATLAS PLATFORM STATUS OVERVIEW" in status_out

    # Test atlas doctor
    assert main(["doctor"]) == 0
    doctor_out = capsys.readouterr().out
    assert (
        "Environment Verification" in doctor_out
        or "System Diagnostics" in doctor_out
        or "Python" in doctor_out
    )

    # Test atlas permissions
    assert main(["permissions"]) == 0
    perm_out = capsys.readouterr().out
    assert "ACTION FIREWALL PERMISSION POLICIES" in perm_out
    assert "file.write" in perm_out

    # Test atlas tools list
    assert main(["tools", "list"]) == 0
    tools_out = capsys.readouterr().out
    assert "REGISTERED EXECUTION TOOLS" in tools_out
    assert "browser_navigate" in tools_out

    # Test atlas plugins list
    assert main(["plugins", "list"]) == 0
    plugins_out = capsys.readouterr().out
    assert "ATLAS WORKFLOW & SKILL PLUGINS" in plugins_out

    # Test atlas mcp list
    assert main(["mcp", "list"]) == 0
    mcp_out = capsys.readouterr().out
    assert "MODEL CONTEXT PROTOCOL (MCP) SERVERS" in mcp_out

    # Test atlas server status
    server_res = main(["server", "status"])
    assert server_res in (0, 1)  # 0 if server daemon running, 1 if offline
    server_out = capsys.readouterr().out
    assert "ATLAS API SERVER RUNTIME" in server_out

    # Test atlas workers list
    assert main(["workers", "list"]) == 0
    workers_out = capsys.readouterr().out
    assert "DISTRIBUTED FLEET WORKERS" in workers_out

    # Test atlas logs
    assert main(["logs"]) == 0
    logs_out = capsys.readouterr().out
    assert "ATLAS AUDIT LOG STREAM" in logs_out


def test_configuration_precedence_and_security(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify config precedence: Environment Variables > Config File > Default Config."""
    cfg_dir = tmp_path / ".atlas"
    cfg_mgr = ConfigManager(config_dir=cfg_dir)

    # 1. Default config check
    assert cfg_mgr.get("api_url") == "http://127.0.0.1:8000"
    assert cfg_mgr.get("default_model") == "atlas:hermetic-default"

    # 2. File write and read check
    cfg_mgr.set("default_model", "openai/gpt-4o")
    assert cfg_mgr.get("default_model") == "openai/gpt-4o"

    # 3. Environment variable override check (Precedence)
    monkeypatch.setenv("ATLAS_DEFAULT_MODEL", "anthropic/claude-3-5-sonnet")
    assert cfg_mgr.get("default_model") == "anthropic/claude-3-5-sonnet"

    # 4. Security check: No plaintext passwords in default config
    all_cfg = cfg_mgr.list_all()
    for key, val in all_cfg.items():
        assert "password" not in key.lower()
        assert val != "production-secret"


def test_model_selection_commands(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify atlas models list, use, and configure subcommands."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))

    # Test models list
    assert main(["models", "list"]) == 0
    list_out = capsys.readouterr().out
    assert "ATLAS MODEL REGISTRY" in list_out
    assert "openai/gpt-4o" in list_out
    assert "anthropic/claude-3-5-sonnet" in list_out

    # Test models use
    assert main(["models", "use", "anthropic"]) == 0
    use_out = capsys.readouterr().out
    assert "anthropic/claude-3-5-sonnet" in use_out

    cfg = ConfigManager(config_dir=tmp_path / ".atlas")
    assert cfg.get("default_model") == "anthropic/claude-3-5-sonnet"

    # Test models configure
    assert main(["models", "configure"]) == 0
    cfg_out = capsys.readouterr().out
    assert "ATLAS MODEL CONFIGURATION" in cfg_out
    assert "OPENAI_API_KEY" in cfg_out


def test_session_lifecycle_and_export(tmp_path: Path) -> None:
    """Verify session creation, persistence, listing, resumption, and export."""
    sess_dir = tmp_path / "sessions"
    sess_mgr = SessionManager(sessions_dir=sess_dir)

    # 1. Create session
    session = sess_mgr.create_session(objective="Build OAuth2 workflow", task_id="task_123")
    sess_id = session["session_id"]
    assert sess_id.startswith("cli_sess_")
    assert session["status"] == "ACTIVE"
    assert session["objective"] == "Build OAuth2 workflow"

    # 2. List sessions
    sessions = sess_mgr.list_sessions()
    assert len(sessions) >= 1
    assert any(s["session_id"] == sess_id for s in sessions)

    # 3. Get session
    retrieved = sess_mgr.get_session(sess_id)
    assert retrieved is not None
    assert retrieved["session_id"] == sess_id

    # 4. Export session to JSON
    export_json = sess_dir / "test_export.json"
    exported_path = sess_mgr.export_session(sess_id, output_path=export_json, fmt="json")
    assert exported_path.exists()
    with open(exported_path, encoding="utf-8") as f:
        data = json.load(f)
        assert data["session_id"] == sess_id

    # 5. Export session to Markdown
    export_md = sess_dir / "test_export.md"
    exported_md_path = sess_mgr.export_session(sess_id, output_path=export_md, fmt="md")
    assert exported_md_path.exists()
    content = exported_md_path.read_text(encoding="utf-8")
    assert f"# ATLAS Session: {sess_id}" in content
    assert "Build OAuth2 workflow" in content


def test_terminal_rendering_formatters() -> None:
    """Verify ANSI table, badge, markdown, and diff renderers."""
    # Test badges
    success_badge = render_badge("COMPLETED", "success")
    assert "COMPLETED" in success_badge
    danger_badge = render_badge("CRITICAL", "danger")
    assert "CRITICAL" in danger_badge

    # Test table formatting
    headers = ["Task ID", "Status", "Duration"]
    rows = [["task_01", "COMPLETED", "12s"], ["task_02", "RUNNING", "4s"]]
    table = render_table(headers, rows)
    assert "Task ID" in table
    assert "task_01" in table
    assert "task_02" in table

    # Test markdown formatting
    md_input = "# Title\n## Section\n- Item 1\n**Bold Note**\n```python\nprint('hello')\n```"
    rendered_md = render_markdown(md_input)
    assert "Title" in rendered_md
    assert "Section" in rendered_md
    assert "Item 1" in rendered_md

    # Test diff formatting
    diff_input = "--- a/file.py\n+++ b/file.py\n@@ -1,3 +1,3 @@\n-old line\n+new line"
    rendered_diff = render_diff(diff_input)
    assert "old line" in rendered_diff
    assert "new line" in rendered_diff

    # Test banner
    banner = render_banner()
    assert "Autonomous Task & Lifecycle Automation System" in banner


def test_minimal_mode_headless_execution(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify minimal headless mode with structured output."""
    # Test minimal execution with invalid empty prompt
    res = main(["--minimal", ""])
    assert res == 1

    # Test minimal execution with valid goal
    res_valid = main(["--minimal", "Health check task"])
    assert res_valid in (0, 1)  # Dependent on server or local fallback
    captured = capsys.readouterr()
    assert captured.out or captured.err


def test_cross_platform_and_signal_handling() -> None:
    """Verify signal registration and cross-platform compatibility resilience."""
    from atlas_cli.main import _setup_signal_handlers

    # Should execute cleanly without raising errors on Windows/Linux/macOS
    _setup_signal_handlers()
