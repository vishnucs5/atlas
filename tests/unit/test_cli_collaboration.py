"""Unit tests for Phase 17 Collaboration, Steering & Compliance CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from atlas_cli.commands.collaboration import (
    run_compliance_export,
    run_compliance_verify,
    run_steering_pause,
    run_steering_resume,
    run_workspace_create,
    run_workspace_inspect,
    run_workspace_lease,
    run_workspace_list,
)
from atlas_cli.conversation.composer import SlashCommandDispatcher
from atlas_cli.main import main
from atlas_collaboration.models import WorkspaceRole
from atlas_collaboration.storage import CollaborationStorage


@pytest.fixture
def mock_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    storage = CollaborationStorage(db_path=tmp_path / "test_cli_collab.db")
    monkeypatch.setattr("atlas_cli.commands.collaboration._get_local_storage", lambda: storage)
    return storage


def test_cli_workspace_create_and_list(
    mock_storage: CollaborationStorage, capsys: pytest.CaptureFixture[str]
):
    """Verify creating and listing workspaces through CLI command."""
    ret_create = run_workspace_create(name="Alpha Project", tenant_id="tenant_eng")
    assert ret_create == 0

    out = capsys.readouterr().out
    assert "Workspace created successfully" in out
    assert "Alpha Project" in out

    ret_list = run_workspace_list()
    assert ret_list == 0
    list_out = capsys.readouterr().out
    assert "Alpha Project" in list_out
    assert "COLLABORATIVE WORKSPACES" in list_out


def test_cli_workspace_inspect_and_lease(
    mock_storage: CollaborationStorage, capsys: pytest.CaptureFixture[str]
):
    """Verify inspecting workspace and acquiring semantic turn leases."""
    mock_storage.save_workspace(
        workspace_id="ws_test_inspect",
        name="Security Audit",
        tenant_id="tenant_sec",
    )
    mock_storage.add_collaborator("ws_test_inspect", "lead@corp.internal", WorkspaceRole.OWNER)

    # Inspect
    ret_inspect = run_workspace_inspect(workspace_id="ws_test_inspect")
    assert ret_inspect == 0
    out_inspect = capsys.readouterr().out
    assert "Security Audit" in out_inspect
    assert "lead@corp.internal" in out_inspect

    # Acquire Turn Lease
    ret_lease = run_workspace_lease(
        workspace_id="ws_test_inspect",
        identity="lead@corp.internal",
        role="OWNER",
        force=True,
    )
    assert ret_lease == 0
    out_lease = capsys.readouterr().out
    assert "Turn lease acquired successfully" in out_lease
    assert "lead@corp.internal" in out_lease


def test_cli_steering_pause_and_resume(
    mock_storage: CollaborationStorage, capsys: pytest.CaptureFixture[str]
):
    """Verify pausing and resuming in-flight workflow execution."""
    mock_storage.save_workspace(
        workspace_id="ws_steer_test",
        name="Payment Pipeline",
    )

    ret_pause = run_steering_pause(
        workspace_id="ws_steer_test",
        reason="Suspicious ledger discrepancy",
        operator_id="operator_dan",
    )
    assert ret_pause == 0
    out_pause = capsys.readouterr().out
    assert "Workspace paused for steering" in out_pause
    assert "Suspicious ledger discrepancy" in out_pause

    # Resume with parameters
    ret_resume = run_steering_resume(
        workspace_id="ws_steer_test",
        params_json=json.dumps({"override_rate": 1.05}),
    )
    assert ret_resume == 0
    out_resume = capsys.readouterr().out
    assert "Workspace execution resumed" in out_resume
    assert "Child Idempotency Key" in out_resume


def test_cli_compliance_export_and_verify(
    tmp_path: Path, mock_storage: CollaborationStorage, capsys: pytest.CaptureFixture[str]
):
    """Verify exporting and validating HMAC-signed compliance proof bundles."""
    mock_storage.save_workspace(
        workspace_id="ws_comp_test",
        name="Healthcare Claims",
    )

    bundle_dest = tmp_path / "test_compliance_bundle.json"
    ret_export = run_compliance_export(
        workspace_id="ws_comp_test",
        output_path=str(bundle_dest),
        frameworks="HIPAA,EU_AI_ACT",
    )
    assert ret_export == 0
    assert bundle_dest.exists()

    out_export = capsys.readouterr().out
    assert "Compliance bundle exported successfully" in out_export

    # Verify bundle
    ret_verify = run_compliance_verify(bundle_path=str(bundle_dest))
    assert ret_verify == 0
    out_verify = capsys.readouterr().out
    assert "COMPLIANCE VERIFICATION" in out_verify
    assert "PASS" in out_verify


def test_cli_slash_command_dispatcher(
    mock_storage: CollaborationStorage, capsys: pytest.CaptureFixture[str]
):
    """Verify /workspace, /steering, /compliance slash commands dispatch cleanly."""
    mock_storage.save_workspace(workspace_id="ws_dummy", name="Dummy Workspace")
    dispatcher = SlashCommandDispatcher(app=MagicMock())

    assert dispatcher.dispatch("/workspace create TestWorkspace") is True
    out_ws = capsys.readouterr().out
    assert "Workspace created successfully" in out_ws

    assert dispatcher.dispatch("/steering pause ws_dummy Anomaly") is True
    assert dispatcher.dispatch("/compliance ws_dummy") is True


def test_main_argparse_routing(
    mock_storage: CollaborationStorage, capsys: pytest.CaptureFixture[str]
):
    """Verify top-level atlas CLI routes to workspace, steering, and compliance subcommands."""
    # atlas workspace list
    ret_ws = main(["workspace", "list"])
    assert ret_ws == 0

    # atlas steering --help
    ret_st = main(["steering"])
    assert ret_st == 0

    # atlas compliance --help
    ret_comp = main(["compliance"])
    assert ret_comp == 0
