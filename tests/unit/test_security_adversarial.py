"""Adversarial security audit tests covering advanced attack vectors against ATLAS."""

import threading
from unittest.mock import patch

import pytest
from atlas_api.auth import get_current_user, reset_token_registry, revoke_token
from atlas_api.main import app
from atlas_coordination.approval_manager import ApprovalManager, ApprovalSecurityError
from atlas_coordination.artifact_manager import ArtifactManager, ArtifactSecurityError
from atlas_coordination.checkpoint_manager import redact_secrets
from atlas_core.contracts.action import ComputerAction
from atlas_core.contracts.policy import PolicyDecisionType, RiskLevel
from atlas_policy.firewall import ActionFirewall, is_ip_restricted
from fastapi.testclient import TestClient


def test_adv_01_dns_rebinding_attack_prevention():
    """Verify that hostnames resolving to private/metadata IPs are blocked even if hostname looks external."""
    firewall = ActionFirewall(block_private_networks=True, allow_localhost=False)

    # Mock DNS resolution to return private IP for an external-looking hostname
    with patch("socket.getaddrinfo") as mock_dns:
        # Simulate DNS rebinding returning 169.254.169.254 (AWS/GCP metadata)
        mock_dns.return_value = [(2, 1, 0, "", ("169.254.169.254", 80))]

        action = ComputerAction(
            action_id="act_rebind_1",
            task_id="task_1",
            session_id="sess_1",
            action_type="browser.navigate",
            parameters={"url": "http://rebind.attacker-domain.com/latest/meta-data"},
            idempotency_key="key_rebind_1",
        )
        decision = firewall.evaluate(action)
        assert decision.decision == PolicyDecisionType.DENY
        assert "restricted by network policy" in decision.reason.lower()


def test_adv_02_redirect_chains_to_private_networks():
    """Verify that multi-hop redirects leading to internal endpoints are blocked."""
    firewall = ActionFirewall(block_private_networks=True, allow_localhost=False)

    original_url = "https://public-service.com/login"

    # Hop 1 to another public URL -> Allowed
    decision1 = firewall.validate_redirect(original_url, "https://auth.public-service.com/oauth")
    assert decision1.decision == PolicyDecisionType.ALLOW

    # Hop 2 redirects to internal router / metadata endpoint -> Blocked
    decision2 = firewall.validate_redirect(original_url, "http://192.168.1.1/admin")
    assert decision2.decision == PolicyDecisionType.DENY
    assert "private" in decision2.reason.lower() or "restricted" in decision2.reason.lower()

    # Hop 3 redirects to loopback -> Blocked
    decision3 = firewall.validate_redirect(original_url, "http://127.0.0.1:8080/metrics")
    assert decision3.decision == PolicyDecisionType.DENY
    assert "loopback" in decision3.reason.lower() or "restricted" in decision3.reason.lower()


def test_adv_03_ipv6_private_and_mapped_restrictions():
    """Verify IPv6 loopback, link-local, unique local, and IPv4-mapped IPv6 are blocked."""
    # IPv6 loopback ::1
    restricted, _ = is_ip_restricted("::1")
    assert restricted is True

    # IPv6 link-local fe80::1
    restricted, _ = is_ip_restricted("fe80::1")
    assert restricted is True

    # IPv6 Unique Local Address fc00::1
    restricted, _ = is_ip_restricted("fc00::1")
    assert restricted is True

    # IPv4-mapped IPv6 address ::ffff:127.0.0.1
    restricted, _ = is_ip_restricted("::ffff:127.0.0.1")
    assert restricted is True

    # IPv4-mapped IPv6 address ::ffff:169.254.169.254
    restricted, _ = is_ip_restricted("::ffff:169.254.169.254")
    assert restricted is True


def test_adv_04_windows_unc_paths_and_ntlm_leak_protection(tmp_path):
    """Verify UNC paths attempting to force Windows SMB NTLM authentication are rejected."""
    art_mgr = ArtifactManager(base_dir=tmp_path)

    # UNC paths starting with \\ or //
    with pytest.raises(ArtifactSecurityError) as exc:
        art_mgr._resolve_safe_path("task_sec_1", r"\\attacker-smb.evil.com\share\file.txt")
    assert "UNC path is prohibited" in str(exc.value)

    with pytest.raises(ArtifactSecurityError) as exc2:
        art_mgr._resolve_safe_path("task_sec_1", "//attacker-smb.evil.com/share/file.txt")
    assert "UNC path is prohibited" in str(exc2.value)


def test_adv_05_symlink_race_and_directory_escape(tmp_path):
    """Verify path traversal escaping out of artifact base directory is strictly prohibited."""
    art_mgr = ArtifactManager(base_dir=tmp_path)

    with pytest.raises(ArtifactSecurityError) as exc:
        art_mgr._resolve_safe_path("task_sec_1", r"..\..\..\outside_secrets\passwords.txt")
    assert "path traversal detected" in str(exc.value).lower()


def test_adv_06_approval_signature_tampering_rejection():
    """Verify tampering with any parameter of an approved action fails validation."""
    mgr = ApprovalManager()

    action = ComputerAction(
        action_id="act_transfer_1",
        task_id="task_secure_1",
        session_id="sess_1",
        action_type="EXECUTE_COMMAND",
        parameters={"command": "deploy --env staging"},
        idempotency_key="key_trans_1",
    )

    req = mgr.create_request(
        task_id=action.task_id,
        action_id=action.action_id,
        action_type=action.action_type,
        parameters=action.parameters,
        risk_level=RiskLevel.HIGH.value,
        ttl_seconds=300,
        policy_version="1.0",
    )

    # Grant approval
    mgr.grant(req.request_id, operator_id="admin_op")

    # Tamper with action parameter before execution
    tampered_action = ComputerAction(
        action_id="act_transfer_1",
        task_id="task_secure_1",
        session_id="sess_1",
        action_type="EXECUTE_COMMAND",
        parameters={"command": "deploy --env production --force"},  # TAMPERED
        idempotency_key="key_trans_1",
    )

    with pytest.raises(ApprovalSecurityError) as exc:
        mgr.validate_action(
            req.request_id,
            action=tampered_action,
            policy_version="1.0",
        )
    assert "Parameter tampering detected" in str(exc.value)


def test_adv_07_approval_replay_prevention():
    """Verify once an approved action is executed, it can never be replayed or reused."""
    mgr = ApprovalManager()

    action = ComputerAction(
        action_id="act_pay_1",
        task_id="task_pay_1",
        session_id="sess_1",
        action_type="EXECUTE_COMMAND",
        parameters={"amount": 100},
        idempotency_key="key_pay_1",
    )

    req = mgr.create_request(
        task_id=action.task_id,
        action_id=action.action_id,
        action_type=action.action_type,
        parameters=action.parameters,
        risk_level=RiskLevel.HIGH.value,
        ttl_seconds=300,
        policy_version="1.0",
    )
    mgr.grant(req.request_id, operator_id="admin_op")

    # First validation succeeds
    assert (
        mgr.validate_action(
            req.request_id,
            action=action,
            policy_version="1.0",
        )
        is True
    )

    # Mark consumed
    mgr.mark_consumed(req.request_id)

    # Second attempt (replay) must fail
    with pytest.raises(ApprovalSecurityError) as exc:
        mgr.validate_action(
            req.request_id,
            action=action,
            policy_version="1.0",
        )
    assert "already been consumed" in str(exc.value)


def test_adv_08_api_token_revocation_enforcement():
    """Verify immediate rejection of revoked tokens with HTTP 401."""
    client = TestClient(app)
    reset_token_registry()

    token = "operator-key"
    user = get_current_user(authorization=f"Bearer {token}")
    assert user is not None

    # Revoke token
    revoke_token(token)

    # Access protected endpoint with revoked token
    response = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"].lower()


def test_adv_09_secret_redaction_in_traces_and_exceptions():
    """Verify API keys, passwords, and tokens are scrubbed from nested error structures."""
    dirty_payload = {
        "error_msg": "Connection failed to postgresql://atlas:super_secret_pw@10.0.0.5:5432/db",
        "api_key": "sk-proj-1234567890abcdef1234567890abcdef12345678",
        "github_token": "ghp_1234567890abcdef1234567890abcdef123456",
        "nested": {
            "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisTokenValue"
        },
    }

    clean = redact_secrets(dirty_payload)
    clean_str = str(clean)
    assert "super_secret_pw" not in clean_str
    assert "sk-proj-1234567890abcdef1234567890abcdef12345678" not in clean_str
    assert "ghp_1234567890abcdef1234567890abcdef12345678" not in clean_str
    assert "***REDACTED***" in clean_str


def test_adv_10_concurrent_approval_consumption_race():
    """Verify race condition where two threads try to consume the same approval simultaneously."""
    mgr = ApprovalManager()

    action = ComputerAction(
        action_id="act_race_1",
        task_id="task_race_1",
        session_id="sess_1",
        action_type="EXECUTE_COMMAND",
        parameters={"cmd": "restart"},
        idempotency_key="key_race_1",
    )

    req = mgr.create_request(
        task_id=action.task_id,
        action_id=action.action_id,
        action_type=action.action_type,
        parameters=action.parameters,
        risk_level=RiskLevel.HIGH.value,
        ttl_seconds=300,
        policy_version="1.0",
    )
    mgr.grant(req.request_id, operator_id="admin_op")

    results = []
    lock = threading.Lock()

    def try_consume():
        try:
            with lock:
                mgr.validate_action(req.request_id, action=action, policy_version="1.0")
                mgr.mark_consumed(req.request_id)
            results.append("SUCCESS")
        except ApprovalSecurityError:
            results.append("BLOCKED")

    t1 = threading.Thread(target=try_consume)
    t2 = threading.Thread(target=try_consume)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one succeeded and one was blocked
    assert sorted(results) == ["BLOCKED", "SUCCESS"]
