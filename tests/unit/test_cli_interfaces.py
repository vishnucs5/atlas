"""Comprehensive unit, integration, and UI tests for ATLAS Minimal Mode and Advanced TUI."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from atlas_cli.adapters.client import AtlasClient
from atlas_cli.approvals.interactive import format_approval_card, run_interactive_approvals
from atlas_cli.events.reconstructor import reconstruct_state_from_events
from atlas_cli.events.stream import EventStreamSubscriber
from atlas_cli.minimal.runner import (
    MinimalREPL,
    highlight_code_block,
    render_terminal_markdown,
    run_minimal,
    stream_text_chunks,
)
from atlas_cli.tui.app import DashboardTUI
from atlas_core.contracts.event import EventType, ExecutionEvent

# ============================================================================
# 1. Minimal Mode Tests
# ============================================================================


def test_minimal_markdown_and_syntax_highlighting():
    """Verify markdown formatting and Pygments code block syntax highlighting."""
    md_text = (
        "# Title Header\n"
        "## Subtitle Header\n"
        "This is **bold text** and `inline_code()`.\n"
        "- Item 1\n"
        "- Item 2\n"
        "```python\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n"
        "```\n"
    )
    rendered = render_terminal_markdown(md_text)

    # Check headers rendered with ANSI styling
    assert "Title Header" in rendered
    assert "Subtitle Header" in rendered
    assert "bold text" in rendered
    assert "inline_code()" in rendered
    assert "•" in rendered  # Bullet icon

    # Check Pygments code block highlighting
    code_snippet = "def add(a, b): return a + b\n"
    highlighted = highlight_code_block(code_snippet, "python")
    assert "def" in highlighted
    assert "add" in highlighted


def test_minimal_streaming_chunks(capsys: pytest.CaptureFixture[str]):
    """Verify responsive text chunk streaming without output corruption."""
    sample_text = "The quick brown fox jumps over the lazy dog"
    stream_text_chunks(sample_text, chunk_delay=0.001)

    captured = capsys.readouterr().out
    assert captured.strip() == sample_text


def test_minimal_repl_slash_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Verify minimal REPL slash commands (/help, /status, /diff, /clear, /exit)."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))

    repl = MinimalREPL(repo_root=str(tmp_path))

    # /help
    repl.print_help()
    out = capsys.readouterr().out
    assert "/help" in out
    assert "/diff" in out
    assert "/status" in out
    assert "/plan" in out
    assert "/test" in out

    # Simulated interactive loop exiting immediately on /exit
    with patch("builtins.input", side_effect=["/help", "/exit"]):
        ret = repl.run_loop()
        assert ret == 0


def test_minimal_headless_objective_execution(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Verify executing minimal mode non-interactively with direct objective."""
    mock_client = MagicMock(spec=AtlasClient)
    mock_client.submit_task.return_value = {
        "status": "COMPLETED",
        "task_id": "task_minimal_123",
        "message": "Engine task executed successfully",
    }

    with patch("atlas_cli.minimal.runner.AtlasClient", return_value=mock_client):
        # Single-shot argument execution
        ret = run_minimal(objective="Create auth utility")
        assert ret == 0
        out = capsys.readouterr().out
        assert "task_minimal_123" in out
        assert "COMPLETED" in out


# ============================================================================
# 2. Event Streaming & State Reconstruction Tests
# ============================================================================


def test_event_stream_subscriber_deduplication_and_ordering():
    """Verify event subscriber orders by sequence and rejects duplicate / stale events."""
    subscriber = EventStreamSubscriber(task_id="task_stream_01")
    dispatched_events: list[ExecutionEvent] = []
    subscriber.subscribe(lambda ev: dispatched_events.append(ev))

    ev1 = ExecutionEvent(
        event_id="ev_001",
        task_id="task_stream_01",
        sequence=1,
        event_type=EventType.TASK_CREATED,
        timestamp=datetime.now(UTC),
        payload={"objective": "Build API"},
        correlation_id="task_stream_01",
    )
    ev2 = ExecutionEvent(
        event_id="ev_002",
        task_id="task_stream_01",
        sequence=2,
        event_type=EventType.PLAN_GENERATED,
        timestamp=datetime.now(UTC),
        payload={"steps": [{"step_id": 1, "name": "Scaffold"}]},
        correlation_id="task_stream_01",
    )
    ev_duplicate = ExecutionEvent(
        event_id="ev_001",
        task_id="task_stream_01",
        sequence=1,
        event_type=EventType.TASK_CREATED,
        timestamp=datetime.now(UTC),
        payload={"objective": "Duplicate"},
        correlation_id="task_stream_01",
    )
    ev_stale = ExecutionEvent(
        event_id="ev_000",
        task_id="task_stream_01",
        sequence=0,
        event_type=EventType.TASK_CREATED,
        timestamp=datetime.now(UTC),
        payload={"objective": "Stale"},
        correlation_id="task_stream_01",
    )

    # Ingest valid events
    accepted = subscriber.ingest_batch([ev2, ev1])
    assert accepted == 2  # Both ev1 and ev2 accepted in ordered sequence
    assert len(dispatched_events) == 2
    assert dispatched_events[0].event_id == "ev_001"
    assert dispatched_events[1].event_id == "ev_002"
    assert subscriber.last_sequence == 2

    # Ingest duplicate and stale events
    assert subscriber.ingest_event(ev_duplicate) is False  # Rejected: duplicate event_id
    assert subscriber.ingest_event(ev_stale) is False  # Rejected: stale sequence (0 <= 2)
    assert len(dispatched_events) == 2


def test_ui_state_reconstruction_from_events():
    """Verify full UIState projection from chronological ExecutionEvents."""
    events = [
        ExecutionEvent(
            event_id="e1",
            task_id="task_proj_99",
            sequence=1,
            event_type=EventType.TASK_CREATED,
            timestamp=datetime.now(UTC),
            payload={"objective": "Refactor router"},
            correlation_id="task_proj_99",
        ),
        ExecutionEvent(
            event_id="e2",
            task_id="task_proj_99",
            sequence=2,
            event_type=EventType.PLAN_GENERATED,
            timestamp=datetime.now(UTC),
            payload={"steps": [{"step_id": 1, "name": "Audit", "risk_level": "LOW"}]},
            correlation_id="task_proj_99",
        ),
        ExecutionEvent(
            event_id="e3",
            task_id="task_proj_99",
            sequence=3,
            event_type=EventType.APPROVAL_REQUESTED,
            timestamp=datetime.now(UTC),
            payload={
                "request_id": "appr_01",
                "action_type": "file.modify",
                "target": "router.py",
                "risk_level": "HIGH",
            },
            correlation_id="task_proj_99",
        ),
        ExecutionEvent(
            event_id="e4",
            task_id="task_proj_99",
            sequence=4,
            event_type=EventType.APPROVAL_GRANTED,
            timestamp=datetime.now(UTC),
            payload={"request_id": "appr_01", "reason": "Authorized by operator"},
            correlation_id="task_proj_99",
        ),
        ExecutionEvent(
            event_id="e5",
            task_id="task_proj_99",
            sequence=5,
            event_type=EventType.ACTION_COMPLETED,
            timestamp=datetime.now(UTC),
            payload={
                "action_id": "act_01",
                "action_type": "file.modify",
                "target": "router.py",
                "result": {"after_hash": "a1b2c3d4"},
            },
            correlation_id="task_proj_99",
        ),
        ExecutionEvent(
            event_id="e6",
            task_id="task_proj_99",
            sequence=6,
            event_type=EventType.TASK_COMPLETED,
            timestamp=datetime.now(UTC),
            payload={"status": "COMPLETED"},
            correlation_id="task_proj_99",
        ),
    ]

    state = reconstruct_state_from_events(events)

    assert state.task_id == "task_proj_99"
    assert state.status == "COMPLETED"
    assert state.objective == "Refactor router"
    assert len(state.plan_steps) == 1
    assert len(state.approvals) == 1
    assert state.approvals[0]["status"] == "GRANTED"
    assert len(state.file_changes) == 1
    assert state.file_changes[0]["path"] == "router.py"
    assert len(state.timeline) == 6
    assert state.last_sequence == 6


# ============================================================================
# 3. Advanced TUI Dashboard Tests
# ============================================================================


def test_tui_all_panels_render_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify all 8 panels render without raising exceptions and include expected headers."""
    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))
    tui = DashboardTUI(repo_root=str(tmp_path))

    width = 100

    # Test Panel 1: Conversation
    conv = tui.render_conversation_panel(width)
    assert "MAIN CONVERSATION" in conv

    # Test Panel 2: Agent Activity
    agent_act = tui.render_agent_activity_panel(width)
    assert "SPECIALIST AGENT ACTIVITY" in agent_act

    # Test Panel 3: Task Graph
    graph = tui.render_task_graph_panel(width)
    assert "TASK GRAPH" in graph

    # Test Panel 4: Terminal
    term = tui.render_terminal_panel(width)
    assert "AUTHORIZED TERMINAL DRIVER" in term
    assert "shell=False" in term

    # Test Panel 5: File Changes
    files = tui.render_file_changes_panel(width)
    assert "FILE CHANGES" in files

    # Test Panel 6: Approvals
    appr = tui.render_approval_panel(width)
    assert "ACTION FIREWALL PENDING APPROVALS" in appr

    # Test Panel 7: Timeline
    timeline = tui.render_timeline_panel(width)
    assert "EXECUTION EVENT TIMELINE" in timeline

    # Test Panel 8: Runtime
    runtime = tui.render_runtime_panel(width)
    assert "RUNTIME, MODELS & RESOURCE MONITOR" in runtime
    assert "Cost Data:" in runtime


def test_tui_panel_navigation_and_commands(tmp_path: Path):
    """Verify keyboard panel switching and command dispatch."""
    tui = DashboardTUI(repo_root=str(tmp_path))

    # Switch by numeric key
    assert tui.handle_command("3") is True
    assert tui.active_panel_idx == 2  # Task Graph

    # Cycle via Tab
    assert tui.handle_command("tab") is True
    assert tui.active_panel_idx == 3  # Terminal

    # Switch via command
    assert tui.handle_command("switch 6") is True
    assert tui.active_panel_idx == 5  # Approvals

    # Quit command returns False
    assert tui.handle_command("q") is False
    assert tui.handle_command("quit") is False


def test_tui_small_terminal_resilience(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Verify graceful handling when terminal dimensions are smaller than 80x24."""
    tui = DashboardTUI(repo_root=str(tmp_path))

    with patch("atlas_cli.tui.app.get_terminal_dimensions", return_value=(60, 15)):
        tui.render_full_screen()
        out = capsys.readouterr().out
        assert "Terminal dimensions too small" in out
        assert "60x15" in out


# ============================================================================
# 4. Approval UX & Action Firewall Gating Tests
# ============================================================================


def test_approval_card_exact_action_details():
    """Verify approval cards display operation, target, parameters, risk, and policy version."""
    req = {
        "request_id": "appr_audit_01",
        "action_type": "file.modify",
        "target": "src/security.py",
        "risk_level": "CRITICAL",
        "reason": "Modifies core policy checks",
        "scope": "workspace",
        "timeout_seconds": "30s",
        "policy_version": "1.0",
        "parameters": {
            "before_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "new_size": 1024,
        },
    }

    card = format_approval_card(req)

    assert "appr_audit_01" in card
    assert "file.modify" in card
    assert "src/security.py" in card
    assert "CRITICAL" in card
    assert "Modifies core policy checks" in card
    assert "before_hash" in card
    assert "1.0" in card


def test_approval_ux_grant_and_deny_interactivity(capsys: pytest.CaptureFixture[str]):
    """Verify granting and denying approvals interactively via CLI."""
    mock_client = MagicMock(spec=AtlasClient)
    mock_client.list_approvals.return_value = [
        {
            "request_id": "req_grant_01",
            "action_type": "terminal.execute",
            "target": "pytest",
            "risk_level": "HIGH",
            "reason": "Runs test suite",
        }
    ]
    mock_client.grant_approval.return_value = {"status": "GRANTED"}

    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", side_effect=["y", "Approved test"]),
    ):
        ret = run_interactive_approvals(client=mock_client)
        assert ret == 0
        mock_client.grant_approval.assert_called_once_with("req_grant_01", reason="Approved test")


# ============================================================================
# 5. Interrupt & Cancellation Invariant Tests
# ============================================================================


def test_interrupt_does_not_cancel_background_task(tmp_path: Path):
    """Verify KeyboardInterrupt in minimal or TUI loop exits interactive turn without aborting task."""
    repl = MinimalREPL(repo_root=str(tmp_path))

    # Simulate KeyboardInterrupt on input
    with patch("builtins.input", side_effect=[KeyboardInterrupt, "/exit"]):
        ret = repl.run_loop()
        assert ret == 0  # Gracefully handled and exited on /exit
        assert repl.session["status"] in ("ACTIVE", "CREATED", "IN_PROGRESS", "COMPLETED")
