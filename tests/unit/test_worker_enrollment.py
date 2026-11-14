"""Unit tests for Worker Identity, Cryptographic Enrollment Authority, and Capability Advertisements."""

import pytest
from atlas_distributed.enrollment import (
    InvalidEnrollmentTokenError,
    SessionZeroInteractiveError,
    WorkerAuthenticationError,
    WorkerEnrollmentAuthority,
    WorkerRevokedError,
)
from atlas_distributed.models import (
    EnrollmentRequest,
    SessionType,
    WorkerCapabilities,
    WorkerHardware,
    WorkerPlatform,
)


@pytest.fixture
def authority() -> WorkerEnrollmentAuthority:
    return WorkerEnrollmentAuthority()


def test_enrollment_token_lifecycle(authority: WorkerEnrollmentAuthority):
    """Verify creation, expiration, single-use limits, and revocation of provisioning tokens."""
    token_secret, token = authority.create_enrollment_token(
        tenant_id="tenant_a",
        expires_in_hours=1.0,
        max_uses=1,
    )

    assert token_secret.startswith("atk_")
    assert token.is_valid() is True
    assert token.tenant_id == "tenant_a"

    # Revocation
    assert authority.revoke_enrollment_token(token.token_id) is True
    assert token.is_valid() is False


def test_successful_worker_enrollment(authority: WorkerEnrollmentAuthority):
    """Verify complete worker enrollment and capability registration."""
    token_secret, _ = authority.create_enrollment_token(tenant_id="tenant_prod", max_uses=2)

    # Windows 11 worker in active user session
    caps_win = WorkerCapabilities(
        platform=WorkerPlatform.WINDOWS,
        os_version="Windows 11 Pro 23H2",
        session_type=SessionType.INTERACTIVE_USER,
        drivers=["pyautogui", "windows_uia", "playwright"],
        browsers=["chrome", "edge"],
        hardware=WorkerHardware(cpu_cores=8, memory_bytes=16 * 1024 * 1024 * 1024, has_gpu=True),
        tags=["interactive", "gpu"],
    )
    req_win = EnrollmentRequest(
        provisioning_token=token_secret,
        hostname="win-desktop-01",
        capabilities=caps_win,
        tenant_id="tenant_prod",
    )

    resp_win = authority.enroll_worker(req_win)
    assert resp_win.worker_id.startswith("worker_windows_")
    assert resp_win.tenant_id == "tenant_prod"
    assert resp_win.auth_token.startswith("wat_")

    worker_record = authority.get_worker(resp_win.worker_id)
    assert worker_record is not None
    assert worker_record.capabilities.supports_interactive_desktop() is True
    assert worker_record.capabilities.hardware.has_gpu is True


def test_invalid_and_expired_token_rejection(authority: WorkerEnrollmentAuthority):
    """Verify rejection of bad, expired, or revoked tokens."""
    # 1. Unknown token
    bad_req = EnrollmentRequest(
        provisioning_token="atk_non_existent",
        hostname="host-1",
        capabilities=WorkerCapabilities(),
    )
    with pytest.raises(
        InvalidEnrollmentTokenError, match="Invalid, expired, exhausted, or revoked"
    ):
        authority.enroll_worker(bad_req)

    # 2. Expired token
    token_sec, token_rec = authority.create_enrollment_token(expires_in_hours=-1.0)
    exp_req = EnrollmentRequest(
        provisioning_token=token_sec,
        hostname="host-2",
        capabilities=WorkerCapabilities(),
    )
    with pytest.raises(InvalidEnrollmentTokenError):
        authority.enroll_worker(exp_req)


def test_tenant_mismatch_rejection(authority: WorkerEnrollmentAuthority):
    """Verify candidate worker cannot use token assigned to a different tenant."""
    token_sec, _ = authority.create_enrollment_token(tenant_id="tenant_alpha")

    mismatch_req = EnrollmentRequest(
        provisioning_token=token_sec,
        hostname="host-mismatch",
        capabilities=WorkerCapabilities(),
        tenant_id="tenant_bravo",
    )
    with pytest.raises(InvalidEnrollmentTokenError, match="does not match request tenant"):
        authority.enroll_worker(mismatch_req)


def test_session_zero_interactive_rejection(authority: WorkerEnrollmentAuthority):
    """Verify that a Windows Session 0 worker is strictly forbidden from claiming interactive desktop automation."""
    token_sec, _ = authority.create_enrollment_token()

    session0_caps = WorkerCapabilities(
        platform=WorkerPlatform.WINDOWS,
        session_type=SessionType.SESSION_0,  # Background non-interactive service!
        drivers=["pyautogui", "windows_uia"],
    )
    req = EnrollmentRequest(
        provisioning_token=token_sec,
        hostname="win-service-host",
        capabilities=session0_caps,
    )

    with pytest.raises(
        SessionZeroInteractiveError, match="Session 0 workers cannot execute interactive desktop"
    ):
        authority.enroll_worker(req)


def test_worker_authentication_and_rotation(authority: WorkerEnrollmentAuthority):
    """Verify credential validation and non-disruptive key rotation."""
    token_sec, _ = authority.create_enrollment_token()
    resp = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token_sec,
            hostname="linux-worker-01",
            capabilities=WorkerCapabilities(platform=WorkerPlatform.LINUX),
        )
    )

    # Valid auth
    worker = authority.authenticate_worker(resp.worker_id, resp.auth_token)
    assert worker.worker_id == resp.worker_id

    # Invalid auth
    with pytest.raises(WorkerAuthenticationError, match="Invalid authentication credentials"):
        authority.authenticate_worker(resp.worker_id, "wat_wrong_token")

    # Rotate credentials
    new_token = authority.rotate_worker_credentials(resp.worker_id, resp.auth_token)
    assert new_token != resp.auth_token

    # Old token fails, new token succeeds
    with pytest.raises(WorkerAuthenticationError):
        authority.authenticate_worker(resp.worker_id, resp.auth_token)
    assert authority.authenticate_worker(resp.worker_id, new_token).worker_id == resp.worker_id


def test_worker_revocation_crl(authority: WorkerEnrollmentAuthority):
    """Verify revoking a worker immediately invalidates all operations."""
    token_sec, _ = authority.create_enrollment_token()
    resp = authority.enroll_worker(
        EnrollmentRequest(
            provisioning_token=token_sec,
            hostname="compromised-host",
            capabilities=WorkerCapabilities(),
        )
    )

    # Revoke worker
    authority.revoke_worker(resp.worker_id, reason="Malware infection detected on endpoint")

    with pytest.raises(WorkerRevokedError, match="has been revoked: Malware infection detected"):
        authority.authenticate_worker(resp.worker_id, resp.auth_token)
