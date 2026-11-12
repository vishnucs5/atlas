"""Unit tests for ApprovalManager and ArtifactManager."""

import time

import pytest
from atlas_coordination.approval_manager import (
    ApprovalManager,
    ApprovalStatus,
)
from atlas_coordination.artifact_manager import (
    ArtifactManager,
    ArtifactSecurityError,
    ArtifactSizeLimitError,
)


def test_approval_manager_lifecycle() -> None:
    """Test approval creation, listing, granting, and denying."""
    mgr = ApprovalManager(default_ttl_seconds=60)

    # Create approval request
    req1 = mgr.create_request(
        task_id="task_123",
        action_id="act_456",
        action_type="browser.fill",
        parameters={"field": "credit_card", "val": "4111"},
        reason="Credit card submission requires authorization",
        risk_level="HIGH",
    )
    assert req1.status == ApprovalStatus.PENDING
    assert req1.task_id == "task_123"

    req2 = mgr.create_request(
        task_id="task_123",
        action_id="act_789",
        action_type="browser.click",
        parameters={"selector": "#buy-now"},
        reason="Checkout confirmation",
        risk_level="CRITICAL",
    )

    # Listing
    all_reqs = mgr.list_requests(task_id="task_123")
    assert len(all_reqs) == 2

    # Grant req1
    granted = mgr.grant(req1.request_id, operator_id="admin_alice", reason="Verified order")
    assert granted.status == ApprovalStatus.GRANTED
    assert granted.operator_id == "admin_alice"
    assert granted.decided_at is not None

    # Cannot grant again
    with pytest.raises(ValueError, match="Cannot grant request"):
        mgr.grant(req1.request_id, operator_id="admin_bob")

    # Deny req2
    denied = mgr.deny(req2.request_id, operator_id="admin_bob", reason="Unintended order")
    assert denied.status == ApprovalStatus.DENIED
    assert denied.operator_id == "admin_bob"
    assert denied.decided_at is not None

    # Filtered listing
    assert len(mgr.list_requests(status=ApprovalStatus.GRANTED)) == 1
    assert len(mgr.list_requests(status=ApprovalStatus.DENIED)) == 1
    assert len(mgr.list_requests(status=ApprovalStatus.PENDING)) == 0


def test_approval_manager_expiration() -> None:
    """Test that overdue approval requests expire automatically."""
    mgr = ApprovalManager(default_ttl_seconds=1)

    req = mgr.create_request(
        task_id="task_timeout",
        action_id="act_timeout",
        action_type="desktop.launch_app",
        parameters={"app_name": "cmd.exe"},
        ttl_seconds=0,  # Expires immediately
    )

    time.sleep(0.01)

    # Fetching evaluates expiration
    fetched = mgr.get_request(req.request_id)
    assert fetched is not None
    assert fetched.status == ApprovalStatus.EXPIRED

    # Cannot grant expired request
    with pytest.raises(ValueError, match="already expired"):
        mgr.grant(req.request_id, operator_id="operator_carol")


def test_artifact_manager_save_and_read(tmp_path) -> None:
    """Test saving and retrieving binary and textual artifacts."""
    art_dir = tmp_path / "artifacts"
    mgr = ArtifactManager(base_dir=art_dir)

    # Binary artifact (e.g. screenshot)
    img_data = b"\x89PNG\r\n\x1a\nfakeimagecontent"
    uri_img = mgr.save_artifact(
        task_id="task_art_1",
        name="screenshot.png",
        data=img_data,
        content_type="image/png",
    )
    assert uri_img == "artifacts://task_art_1/screenshot.png"

    read_data, ctype = mgr.read_artifact("task_art_1", "screenshot.png")
    assert read_data == img_data
    assert ctype == "image/png"

    # Text artifact with sensitive secret redaction
    mgr.save_artifact(
        task_id="task_art_1",
        name="response.json",
        data={"api_key": "sk-secret-12345", "status": "ok"},
    )

    read_json_bytes, json_ctype = mgr.read_artifact("task_art_1", "response.json")
    read_str = read_json_bytes.decode("utf-8")
    assert json_ctype == "application/json"
    assert "sk-secret-12345" not in read_str
    assert "***REDACTED***" in read_str

    # List artifacts
    items = mgr.list_artifacts("task_art_1")
    assert len(items) == 2
    names = [item["name"] for item in items]
    assert "screenshot.png" in names
    assert "response.json" in names

    # Delete artifact
    assert mgr.delete_artifact("task_art_1", "screenshot.png") is True
    assert len(mgr.list_artifacts("task_art_1")) == 1


def test_artifact_manager_security_traversal(tmp_path) -> None:
    """Verify ArtifactManager strictly prevents path traversal attacks."""
    art_dir = tmp_path / "artifacts"
    mgr = ArtifactManager(base_dir=art_dir)

    # Traversal in task_id
    with pytest.raises(ArtifactSecurityError, match="Invalid task_id"):
        mgr.save_artifact(task_id="../escaped_task", name="evil.txt", data="bad")

    # Traversal in name
    with pytest.raises(ArtifactSecurityError, match="Path traversal detected"):
        mgr.save_artifact(task_id="task_safe", name="../../etc/shadow", data="bad")

    with pytest.raises(ArtifactSecurityError, match="Path traversal detected"):
        mgr.read_artifact("task_safe", "../parent.txt")


def test_artifact_manager_size_limit(tmp_path) -> None:
    """Verify ArtifactManager strictly rejects payloads exceeding max_size_bytes."""
    art_dir = tmp_path / "artifacts"
    mgr = ArtifactManager(base_dir=art_dir, max_size_bytes=100)

    oversized = b"X" * 101
    with pytest.raises(ArtifactSizeLimitError, match="exceeds maximum"):
        mgr.save_artifact("task_size", "big.bin", oversized)
