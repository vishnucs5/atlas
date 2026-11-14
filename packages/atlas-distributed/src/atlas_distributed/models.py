"""Domain contracts and data models for ATLAS Distributed Execution Network."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from atlas_core.contracts.worker import WorkerStatus
from pydantic import BaseModel, ConfigDict, Field


class WorkerPlatform(StrEnum):
    """Underlying operating system and execution platform of a worker."""

    WINDOWS = "windows"
    LINUX = "linux"
    DARWIN = "darwin"
    CONTAINER = "container"


class SessionType(StrEnum):
    """Execution session environment type."""

    INTERACTIVE_USER = "interactive_user"  # Active desktop session with GUI display
    HEADLESS = "headless"                  # Headless VM/server (e.g. Linux bare-metal)
    SESSION_0 = "session_0"                # Windows non-interactive service isolation


class WorkerHardware(BaseModel):
    """Hardware specifications and capacity constraints of a worker node."""

    model_config = ConfigDict(validate_assignment=True)

    cpu_cores: int = 4
    memory_bytes: int = 8 * 1024 * 1024 * 1024  # 8 GB default
    has_gpu: bool = False
    gpu_name: str | None = None


class WorkerCapabilities(BaseModel):
    """Detailed advertisement of platforms, drivers, tools, and hardware."""

    model_config = ConfigDict(validate_assignment=True)

    platform: WorkerPlatform = WorkerPlatform.LINUX
    os_version: str = "Linux-6.x"
    architecture: str = "x86_64"
    session_type: SessionType = SessionType.HEADLESS
    drivers: list[str] = Field(default_factory=lambda: ["playwright", "bash"])
    browsers: list[str] = Field(default_factory=lambda: ["chromium"])
    hardware: WorkerHardware = Field(default_factory=WorkerHardware)
    tags: list[str] = Field(default_factory=list)
    software_version: str = "0.1.0"
    max_concurrent_tasks: int = 2

    def supports_interactive_desktop(self) -> bool:
        """Verify whether this worker can execute interactive Windows/GUI automation."""
        return (
            self.platform == WorkerPlatform.WINDOWS
            and self.session_type == SessionType.INTERACTIVE_USER
            and any(d in self.drivers for d in ["pyautogui", "windows_uia", "desktop"])
        )


class EnrollmentToken(BaseModel):
    """Cryptographic provisioning token used to authorize worker registration."""

    model_config = ConfigDict(validate_assignment=True)

    token_id: str
    token_secret_hash: str
    tenant_id: str = "default"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    max_uses: int = 1
    uses_count: int = 0
    is_revoked: bool = False
    created_by: str = "admin"

    def is_valid(self, at_time: datetime | None = None) -> bool:
        """Check if provisioning token is unrevoked, unexpired, and has remaining uses."""
        now = at_time or datetime.now(UTC)
        if self.is_revoked:
            return False
        if now >= self.expires_at:
            return False
        if self.max_uses > 0 and self.uses_count >= self.max_uses:
            return False
        return True


class EnrollmentRequest(BaseModel):
    """Request payload submitted by a candidate worker to join the network."""

    model_config = ConfigDict(validate_assignment=True)

    provisioning_token: str
    hostname: str
    capabilities: WorkerCapabilities
    tenant_id: str = "default"
    worker_metadata: dict[str, Any] = Field(default_factory=dict)


class EnrollmentResponse(BaseModel):
    """Response payload returned upon successful worker enrollment."""

    model_config = ConfigDict(validate_assignment=True)

    worker_id: str
    tenant_id: str
    auth_token: str
    control_plane_version: str = "0.1.0"
    heartbeat_interval_seconds: float = 5.0
    lease_ttl_seconds: float = 30.0


class WorkerIdentity(BaseModel):
    """Control plane record tracking an enrolled, authenticated worker node."""

    model_config = ConfigDict(validate_assignment=True)

    worker_id: str
    tenant_id: str = "default"
    hostname: str
    auth_token_hash: str
    status: WorkerStatus = WorkerStatus.IDLE
    capabilities: WorkerCapabilities
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_heartbeat_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_revoked: bool = False
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"


class AssignmentPayload(BaseModel):
    """Formal task assignment dispatched to an enrolled worker."""

    model_config = ConfigDict(validate_assignment=True)

    assignment_id: str
    task_id: str
    subtask_id: str | None = None
    worker_id: str
    tenant_id: str = "default"
    lease_id: str
    generation: int = 1
    objective: str
    action_type: str = "task_execution"
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: list[str] = Field(default_factory=list)
    policy_context: dict[str, Any] = Field(default_factory=dict)
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    timeout_seconds: float = 300.0


class AssignmentStatus(StrEnum):
    """Lifecycle state of an assignment on a worker node."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REASSIGNED = "REASSIGNED"


class AssignmentResult(BaseModel):
    """Result returned by a worker upon completion of an assignment."""

    model_config = ConfigDict(validate_assignment=True)

    assignment_id: str
    task_id: str
    worker_id: str
    generation: int
    status: AssignmentStatus
    output: dict[str, Any] = Field(default_factory=dict)
    deliverables: dict[str, Any] = Field(default_factory=dict)
    verification_evidence: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, str]] = Field(default_factory=list)
    error: str | None = None
    execution_duration_ms: float = 0.0
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProtocolMessageType(StrEnum):
    """Supported message frame types in Remote Execution Protocol."""

    ENROLL_REQUEST = "ENROLL_REQUEST"
    ENROLL_RESPONSE = "ENROLL_RESPONSE"
    HEARTBEAT = "HEARTBEAT"
    HEARTBEAT_ACK = "HEARTBEAT_ACK"
    ASSIGNMENT_OFFER = "ASSIGNMENT_OFFER"
    ASSIGNMENT_ACK = "ASSIGNMENT_ACK"
    PROGRESS_EVENT = "PROGRESS_EVENT"
    ACTION_REQUEST = "ACTION_REQUEST"
    ACTION_RESULT = "ACTION_RESULT"
    CANCEL_DIRECTIVE = "CANCEL_DIRECTIVE"
    ASSIGNMENT_COMPLETE = "ASSIGNMENT_COMPLETE"
    RECONNECT_HANDSHAKE = "RECONNECT_HANDSHAKE"


class ProtocolEnvelope(BaseModel):
    """Standard authenticated transport envelope for all distributed messages."""

    model_config = ConfigDict(validate_assignment=True)

    protocol_version: str = "ATLAS-REP/1.0"
    message_id: str
    message_type: ProtocolMessageType
    sender_id: str
    recipient_id: str
    tenant_id: str = "default"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sequence_number: int = 1
    payload: dict[str, Any] = Field(default_factory=dict)
    signature: str = ""
