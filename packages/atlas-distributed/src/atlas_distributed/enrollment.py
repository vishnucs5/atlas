"""Worker Enrollment Authority managing provisioning tokens, worker identities, and authentication."""

import hashlib
import hmac
import secrets
import threading
from datetime import UTC, datetime, timedelta

from atlas_core.contracts.worker import WorkerStatus

from atlas_distributed.models import (
    EnrollmentRequest,
    EnrollmentResponse,
    EnrollmentToken,
    SessionType,
    WorkerIdentity,
    WorkerPlatform,
)


class EnrollmentError(Exception):
    """Base exception for all worker enrollment and authentication failures."""


class InvalidEnrollmentTokenError(EnrollmentError):
    """Raised when an enrollment token is invalid, expired, revoked, or exhausted."""


class WorkerAuthenticationError(EnrollmentError):
    """Raised when a worker presents invalid or unrecognized authentication credentials."""


class WorkerRevokedError(EnrollmentError):
    """Raised when an action is attempted by a revoked worker."""


class SessionZeroInteractiveError(EnrollmentError):
    """Raised when a Windows Session 0 worker attempts to claim interactive desktop capabilities."""


def hash_secret(secret: str) -> str:
    """Compute secure SHA-256 digest of an authentication secret or token."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class WorkerEnrollmentAuthority:
    """Manages secure cryptographic enrollment, tokens, and mutual authentication for workers."""

    def __init__(self, master_key: str | None = None) -> None:
        self._master_key = master_key or secrets.token_hex(32)
        self._tokens: dict[str, EnrollmentToken] = {}
        self._workers: dict[str, WorkerIdentity] = {}
        self._lock = threading.RLock()

    def create_enrollment_token(
        self,
        tenant_id: str = "default",
        expires_in_hours: float = 24.0,
        max_uses: int = 1,
        created_by: str = "admin",
    ) -> tuple[str, EnrollmentToken]:
        """Generate a cryptographically random provisioning token for worker enrollment."""
        with self._lock:
            token_secret = f"atk_{secrets.token_urlsafe(32)}"
            token_id = f"tok_{secrets.token_hex(8)}"
            token_hash = hash_secret(token_secret)

            now = datetime.now(UTC)
            expires_at = now + timedelta(hours=expires_in_hours)

            token_record = EnrollmentToken(
                token_id=token_id,
                token_secret_hash=token_hash,
                tenant_id=tenant_id,
                created_at=now,
                expires_at=expires_at,
                max_uses=max_uses,
                uses_count=0,
                is_revoked=False,
                created_by=created_by,
            )
            self._tokens[token_hash] = token_record
            return token_secret, token_record

    def revoke_enrollment_token(self, token_id: str) -> bool:
        """Revoke a provisioning token, preventing any future enrollments with it."""
        with self._lock:
            for token_record in self._tokens.values():
                if token_record.token_id == token_id:
                    token_record.is_revoked = True
                    return True
            return False

    def enroll_worker(self, request: EnrollmentRequest) -> EnrollmentResponse:
        """Validate provisioning token and issue permanent worker identity and credentials."""
        with self._lock:
            token_hash = hash_secret(request.provisioning_token)
            token_record = self._tokens.get(token_hash)

            if not token_record or not token_record.is_valid():
                raise InvalidEnrollmentTokenError(
                    "Invalid, expired, exhausted, or revoked provisioning token."
                )

            if token_record.tenant_id != request.tenant_id:
                raise InvalidEnrollmentTokenError(
                    f"Token tenant '{token_record.tenant_id}' does not match request tenant '{request.tenant_id}'."
                )

            # Invariant: Windows Session 0 cannot claim interactive desktop capability
            caps = request.capabilities
            if (
                caps.platform == WorkerPlatform.WINDOWS
                and caps.session_type == SessionType.SESSION_0
                and any(d in caps.drivers for d in ["pyautogui", "windows_uia", "desktop"])
            ):
                raise SessionZeroInteractiveError(
                    "Windows Session 0 workers cannot execute interactive desktop automation. Run in an active user session."
                )

            # Consume token use
            token_record.uses_count += 1

            # Generate unique worker identity and authentication token
            worker_id = f"worker_{request.capabilities.platform}_{secrets.token_hex(6)}"
            auth_token = f"wat_{secrets.token_urlsafe(32)}"
            auth_token_hash = hash_secret(auth_token)

            now = datetime.now(UTC)
            worker_record = WorkerIdentity(
                worker_id=worker_id,
                tenant_id=request.tenant_id,
                hostname=request.hostname,
                auth_token_hash=auth_token_hash,
                status=WorkerStatus.IDLE,
                capabilities=request.capabilities,
                registered_at=now,
                last_heartbeat_at=now,
                is_revoked=False,
                metadata=request.worker_metadata,
            )

            self._workers[worker_id] = worker_record

            return EnrollmentResponse(
                worker_id=worker_id,
                tenant_id=request.tenant_id,
                auth_token=auth_token,
                control_plane_version="0.1.0",
                heartbeat_interval_seconds=5.0,
                lease_ttl_seconds=30.0,
            )

    def authenticate_worker(self, worker_id: str, auth_token: str) -> WorkerIdentity:
        """Verify worker identity and authentication token."""
        with self._lock:
            worker = self._workers.get(worker_id)
            if not worker:
                raise WorkerAuthenticationError(f"Worker '{worker_id}' is not enrolled.")

            if worker.is_revoked:
                raise WorkerRevokedError(
                    f"Worker '{worker_id}' has been revoked: {worker.revocation_reason or 'No reason provided'}"
                )

            provided_hash = hash_secret(auth_token)
            if not hmac.compare_digest(worker.auth_token_hash, provided_hash):
                raise WorkerAuthenticationError(f"Invalid authentication credentials for worker '{worker_id}'.")

            return worker

    def rotate_worker_credentials(self, worker_id: str, current_token: str) -> str:
        """Issue a new authentication credential for an enrolled worker."""
        with self._lock:
            worker = self.authenticate_worker(worker_id, current_token)
            new_auth_token = f"wat_{secrets.token_urlsafe(32)}"
            worker.auth_token_hash = hash_secret(new_auth_token)
            return new_auth_token

    def revoke_worker(self, worker_id: str, reason: str = "Administrative revocation") -> None:
        """Revoke a worker identity immediately, denying all future requests."""
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker:
                worker.is_revoked = True
                worker.revoked_at = datetime.now(UTC)
                worker.revocation_reason = reason
                worker.status = WorkerStatus.TERMINATED

    def get_worker(self, worker_id: str) -> WorkerIdentity | None:
        """Retrieve worker identity record by ID."""
        with self._lock:
            return self._workers.get(worker_id)

    def list_workers(
        self,
        tenant_id: str | None = None,
        include_revoked: bool = False,
    ) -> list[WorkerIdentity]:
        """List registered workers matching optional tenant filter."""
        with self._lock:
            results = []
            for w in self._workers.values():
                if tenant_id and w.tenant_id != tenant_id:
                    continue
                if not include_revoked and w.is_revoked:
                    continue
                results.append(w)
            return results
