"""Unit tests verifying Milestone 1 security hardening and threat mitigations."""

import io
import time
import zipfile

import pytest
from atlas_api.auth import (
    Role,
    get_current_user,
    reset_token_registry,
    revoke_token,
    set_token_expiry,
)
from atlas_api.main import app
from atlas_coordination.approval_manager import (
    ApprovalManager,
    ApprovalSecurityError,
)
from atlas_coordination.artifact_manager import ArtifactManager, ArtifactSecurityError
from atlas_coordination.checkpoint_manager import redact_secrets
from atlas_core.contracts.action import ComputerAction
from atlas_policy.firewall import (
    ActionFirewall,
)
from atlas_storage.sqlite import SQLiteStorage
from fastapi.testclient import TestClient


def test_approval_parameter_tampering_rejected() -> None:
    """Verify that tampering with any action parameter invalidates the approval signature."""
    mgr = ApprovalManager()
    original_params = {"url": "https://bank.example.com/transfer", "amount": 100}
    req = mgr.create_request(
        task_id="task_sec_01",
        action_id="act_01",
        action_type="payment.transfer",
        parameters=original_params,
        reason="Authorize payment",
        risk_level="CRITICAL",
    )
    mgr.grant(req.request_id, operator_id="officer_bob")

    # Action matching exact parameters passes validation
    valid_action = ComputerAction(
        action_id="act_01",
        task_id="task_sec_01",
        session_id="sess_sec_01",
        action_type="payment.transfer",
        parameters={"amount": 100, "url": "https://bank.example.com/transfer"},  # canonical sorting
        idempotency_key="idemp_sec_01",
    )
    validated = mgr.validate_action(req.request_id, valid_action)
    assert validated is True

    # Tampered parameter value must be rejected
    tampered_action = ComputerAction(
        action_id="act_01",
        task_id="task_sec_01",
        session_id="sess_sec_01",
        action_type="payment.transfer",
        parameters={"amount": 9999, "url": "https://bank.example.com/transfer"},
        idempotency_key="idemp_sec_01",
    )
    with pytest.raises(ApprovalSecurityError, match="Parameter tampering detected"):
        mgr.validate_action(req.request_id, tampered_action)

    # Added unexpected parameter must be rejected
    injected_action = ComputerAction(
        action_id="act_01",
        task_id="task_sec_01",
        session_id="sess_sec_01",
        action_type="payment.transfer",
        parameters={
            "amount": 100,
            "url": "https://bank.example.com/transfer",
            "destination": "evil_acc",
        },
        idempotency_key="idemp_sec_01",
    )
    with pytest.raises(ApprovalSecurityError, match="Parameter tampering detected"):
        mgr.validate_action(req.request_id, injected_action)


def test_approval_replay_rejected() -> None:
    """Verify that an approved action cannot be executed/validated more than once."""
    mgr = ApprovalManager()
    params = {"command": "restart-service"}
    req = mgr.create_request(
        task_id="task_sec_02",
        action_id="act_02",
        action_type="system.restart",
        parameters=params,
        reason="Service restart",
        risk_level="HIGH",
    )
    mgr.grant(req.request_id, operator_id="officer_alice")

    action = ComputerAction(
        action_id="act_02",
        task_id="task_sec_02",
        session_id="sess_sec_02",
        action_type="system.restart",
        parameters=params,
        idempotency_key="idemp_sec_02",
    )
    # First execution succeeds and marks consumed
    mgr.validate_action(req.request_id, action)
    mgr.mark_consumed(req.request_id)

    # Second attempt (replay) must be rejected
    with pytest.raises(ApprovalSecurityError, match="already been consumed"):
        mgr.validate_action(req.request_id, action)


def test_approval_expiration_rejected() -> None:
    """Verify that expired approvals cannot be validated."""
    mgr = ApprovalManager()
    req = mgr.create_request(
        task_id="task_sec_03",
        action_id="act_03",
        action_type="file.delete",
        parameters={"path": "/var/log/app.log"},
        ttl_seconds=-10,  # Pre-expired
    )
    mgr._requests[req.request_id].status = (  # Simulate expired
        mgr._requests[req.request_id].status
    )

    action = ComputerAction(
        action_id="act_03",
        task_id="task_sec_03",
        session_id="sess_sec_03",
        action_type="file.delete",
        parameters={"path": "/var/log/app.log"},
        idempotency_key="idemp_sec_03",
    )
    with pytest.raises(ApprovalSecurityError, match="EXPIRED"):
        mgr.validate_action(req.request_id, action)


def test_ssrf_private_network_blocking() -> None:
    """Verify ActionFirewall blocks loopback, private subnets, and metadata services."""
    firewall = ActionFirewall(block_private_networks=True, allow_localhost=False)

    # 1. AWS/GCP cloud metadata IP
    act_meta = ComputerAction(
        action_id="act_ssrf_1",
        task_id="task_ssrf_1",
        session_id="sess_ssrf_1",
        action_type="browser.navigate",
        parameters={"url": "http://169.254.169.254/latest/meta-data"},
        idempotency_key="idemp_ssrf_1",
    )
    decision = firewall.evaluate(act_meta)
    assert decision.decision.value == "DENY"
    assert "restricted by network policy" in decision.reason

    # 2. RFC 1918 Private IP (10.0.0.1)
    act_rfc10 = ComputerAction(
        action_id="act_ssrf_2",
        task_id="task_ssrf_2",
        session_id="sess_ssrf_2",
        action_type="browser.navigate",
        parameters={"url": "http://10.0.0.1/admin"},
        idempotency_key="idemp_ssrf_2",
    )
    decision = firewall.evaluate(act_rfc10)
    assert decision.decision.value == "DENY"

    # 3. Localhost loopback when disallowed
    act_local = ComputerAction(
        action_id="act_ssrf_3",
        task_id="task_ssrf_3",
        session_id="sess_ssrf_3",
        action_type="browser.navigate",
        parameters={"url": "http://127.0.0.1:8080/metrics"},
        idempotency_key="idemp_ssrf_3",
    )
    decision = firewall.evaluate(act_local)
    assert decision.decision.value == "DENY"

    # 4. Localhost allowed when explicitly enabled
    firewall_dev = ActionFirewall(block_private_networks=True, allow_localhost=True)
    decision_dev = firewall_dev.evaluate(act_local)
    assert decision_dev.decision.value == "ALLOW"


def test_ssrf_redirect_validation() -> None:
    """Verify that redirects from public origins to internal IPs are rejected."""
    firewall = ActionFirewall(block_private_networks=True)
    decision = firewall.validate_redirect(
        from_url="https://public.example.com",
        to_url="http://169.254.169.254/secret",
    )
    assert decision.decision.value == "DENY"
    assert "violated policy" in decision.reason


def test_filesystem_unc_path_blocking(tmp_path) -> None:
    """Verify ArtifactManager rejects Windows UNC and network share paths."""
    art_mgr = ArtifactManager(base_dir=tmp_path)

    with pytest.raises(ArtifactSecurityError, match="UNC path is prohibited"):
        art_mgr.save_artifact("task_fs_1", r"\\evil-server\share\dump.txt", "payload")

    with pytest.raises(ArtifactSecurityError, match="UNC path is prohibited"):
        art_mgr.save_artifact("task_fs_1", "//evil-server/share/dump.txt", "payload")


def test_filesystem_windows_reserved_names_blocking(tmp_path) -> None:
    """Verify ArtifactManager rejects Windows reserved device filenames."""
    art_mgr = ArtifactManager(base_dir=tmp_path)

    for reserved in ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"]:
        with pytest.raises(ArtifactSecurityError, match="reserved device filename"):
            art_mgr.save_artifact("task_fs_2", f"{reserved}.txt", "payload")

        with pytest.raises(ArtifactSecurityError, match="reserved device filename"):
            art_mgr.save_artifact("task_fs_2", reserved.lower(), "payload")


def test_archive_decompression_bomb_guard(tmp_path) -> None:
    """Verify safe_extract_archive rejects archives exceeding maximum size bounds."""
    art_mgr = ArtifactManager(base_dir=tmp_path)

    # Create in-memory zip archive with 10 KB uncompressed data
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("large_file.txt", "A" * 10_000)
    zip_bytes = buffer.getvalue()

    # Save zip archive as an artifact first
    art_mgr.save_artifact("task_zip_1", "archive.zip", zip_bytes, content_type="application/zip")

    # Extract with small uncompressed quota (500 bytes) -> must reject
    with pytest.raises(ArtifactSecurityError, match="exceeded size limit"):
        art_mgr.safe_extract_archive(
            task_id="task_zip_1",
            archive_name="archive.zip",
            max_uncompressed_bytes=500,
        )


def test_secret_redaction_comprehensive() -> None:
    """Verify multi-pattern secret scrubbers across Anthropic, OpenAI, GitHub, AWS, and PEM keys."""
    raw_text = (
        "Logs: OpenAI sk-1234567890abcdef1234567890abcdef and "
        "Anthropic sk-ant-api03-1234567890abcdef1234567890abcdef_secret, "
        "GitHub ghp_123456789012345678901234567890123456, "
        "AWS AKIAIOSFODNN7EXAMPLE, "
        "Key: -----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
    )
    redacted = redact_secrets(raw_text)

    assert "sk-1234567890" not in redacted
    assert "sk-ant-" not in redacted
    assert "ghp_" not in redacted
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "BEGIN RSA PRIVATE KEY" not in redacted
    assert "***REDACTED***" in redacted


def test_api_token_revocation_and_expiration() -> None:
    """Verify API token revocation list and expiration timestamps in auth module."""
    reset_token_registry()
    try:
        # Initially valid operator key
        user = get_current_user(authorization="Bearer operator-key")
        assert user.role == Role.OPERATOR

        # Explicit revocation
        revoke_token("operator-key")
        with pytest.raises(Exception) as exc_info:
            get_current_user(authorization="Bearer operator-key")
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail

        # Expiration timestamp check
        set_token_expiry("admin-key", time.time() - 5.0)  # Expired 5 seconds ago
        with pytest.raises(Exception) as exc_info:
            get_current_user(authorization="Bearer admin-key")
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail
    finally:
        reset_token_registry()


def test_api_cross_tenant_isolation() -> None:
    """Verify that private tasks owned by one user cannot be viewed by another non-admin user."""
    storage = SQLiteStorage(":memory:")
    storage.initialize()
    app.state.storage = storage
    app.state.runtime = None
    client = TestClient(app)

    try:
        # 1. User Operator submits a private task
        op_res = client.post(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer operator-key"},
            json={
                "objective": "Confidential financial reconciliation",
                "metadata": {"private": True},
            },
        )
        assert op_res.status_code == 201
        task_id = op_res.json()["task_id"]

        # 2. Same operator can retrieve the private task
        op_get = client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"Authorization": "Bearer operator-key"},
        )
        assert op_get.status_code == 200

        # 3. Viewer (different identity) attempting to retrieve private task gets 403 Forbidden
        viewer_get = client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"Authorization": "Bearer viewer-key"},
        )
        assert viewer_get.status_code == 403
        assert "Forbidden" in viewer_get.json()["detail"]

        # 4. Viewer listing tasks does not see the private task
        viewer_list = client.get(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer viewer-key"},
        )
        assert viewer_list.status_code == 200
        assert not any(t["task_id"] == task_id for t in viewer_list.json())

        # 5. Admin can retrieve private task
        admin_get = client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"Authorization": "Bearer admin-key"},
        )
        assert admin_get.status_code == 200
    finally:
        storage.close()
        app.state.storage = None
        app.state.runtime = None
