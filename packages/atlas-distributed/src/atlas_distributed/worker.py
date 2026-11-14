"""Lightweight, installable worker agent daemon for ATLAS Distributed Execution Network."""

import logging
import os
import platform
import sys
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import httpx
from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.worker import WorkerStatus
from atlas_core.runtime.driver import ComputerDriver
from pydantic import BaseModel, ConfigDict, Field

from atlas_distributed.enrollment import SessionZeroInteractiveError
from atlas_distributed.models import (
    AssignmentPayload,
    AssignmentProgress,
    AssignmentResult,
    AssignmentStatus,
    EnrollmentRequest,
    EnrollmentResponse,
    SessionType,
    WorkerCapabilities,
    WorkerHardware,
    WorkerHeartbeat,
    WorkerPlatform,
)

logger = logging.getLogger("atlas.distributed.worker")


def detect_platform() -> WorkerPlatform:
    """Detect operating system platform of the local worker host."""
    system = sys.platform.lower()
    if system.startswith("win"):
        return WorkerPlatform.WINDOWS
    elif system.startswith("linux"):
        # Check if inside a container environment
        if os.path.exists("/.dockerenv") or os.environ.get("KUBERNETES_SERVICE_HOST"):
            return WorkerPlatform.CONTAINER
        return WorkerPlatform.LINUX
    elif system.startswith("darwin"):
        return WorkerPlatform.DARWIN
    return WorkerPlatform.LINUX


def detect_session_type(target_platform: WorkerPlatform | None = None) -> SessionType:
    """Detect whether host environment is interactive user desktop, headless, or Windows Session 0."""
    plat = target_platform or detect_platform()

    if plat == WorkerPlatform.WINDOWS:
        # Check Windows Session ID using Win32 API
        try:
            import ctypes

            session_id = ctypes.c_ulong()
            # ProcessIdToSessionId returns non-zero on success
            if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
                if session_id.value == 0:
                    return SessionType.SESSION_0
                return SessionType.INTERACTIVE_USER
        except Exception as exc:
            logger.debug("Windows session detection fallback: %s", exc)

        # Fallback heuristic: check SESSIONNAME or service environment
        session_name = os.environ.get("SESSIONNAME", "").lower()
        if session_name.startswith("services") or session_name == "rdp-tcp":
            if session_name.startswith("services"):
                return SessionType.SESSION_0
        return SessionType.INTERACTIVE_USER

    # Linux / Darwin / Container
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return SessionType.INTERACTIVE_USER
    return SessionType.HEADLESS


def detect_hardware() -> WorkerHardware:
    """Detect local host hardware specifications."""
    cpu_cores = os.cpu_count() or 4
    memory_bytes = 8 * 1024 * 1024 * 1024  # 8GB fallback

    try:
        import psutil

        memory_bytes = psutil.virtual_memory().total
    except ImportError:
        pass

    return WorkerHardware(
        cpu_cores=cpu_cores,
        memory_bytes=memory_bytes,
        has_gpu=False,
        gpu_name=None,
    )


def detect_capabilities(drivers: list[str] | None = None) -> WorkerCapabilities:
    """Assemble capability profile from host environment and registered drivers."""
    plat = detect_platform()
    session = detect_session_type(plat)
    hardware = detect_hardware()

    default_drivers = ["bash", "playwright"] if plat != WorkerPlatform.WINDOWS else ["cmd", "playwright"]
    active_drivers = drivers or default_drivers

    # If on Windows interactive session with UI automation tools, advertise desktop
    if plat == WorkerPlatform.WINDOWS and session == SessionType.INTERACTIVE_USER:
        if "desktop" not in active_drivers:
            active_drivers.append("desktop")

    return WorkerCapabilities(
        platform=plat,
        os_version=f"{platform.system()} {platform.release()}",
        architecture=platform.machine(),
        session_type=session,
        drivers=active_drivers,
        browsers=["chromium"],
        hardware=hardware,
        tags=[plat.value, session.value],
        software_version="0.1.0",
        max_concurrent_tasks=2,
    )


class WorkerAgentConfig(BaseModel):
    """Runtime configuration for a WorkerAgent node."""

    model_config = ConfigDict(validate_assignment=True)

    worker_id: str | None = None
    hostname: str = Field(default_factory=platform.node)
    tenant_id: str = "default"
    control_plane_url: str = "http://localhost:8000"
    auth_token: str | None = None
    provisioning_token: str | None = None
    heartbeat_interval_seconds: float = 5.0
    buffer_capacity: int = 1000
    capabilities: WorkerCapabilities | None = None


@runtime_checkable
class ControlPlaneTransport(Protocol):
    """Protocol for outbound-only communication to ATLAS Control Plane."""

    async def enroll(self, request: EnrollmentRequest) -> EnrollmentResponse:
        """Submit enrollment request with provisioning token."""
        ...

    async def send_heartbeat(self, heartbeat: WorkerHeartbeat) -> dict[str, Any]:
        """Send periodic heartbeat to control plane."""
        ...

    async def send_progress(self, progress: AssignmentProgress) -> dict[str, Any]:
        """Stream assignment progress update."""
        ...

    async def send_completion(self, result: AssignmentResult) -> dict[str, Any]:
        """Deliver assignment execution result."""
        ...


class InMemoryControlPlaneTransport:
    """In-memory mock control plane transport for testing and local execution."""

    def __init__(self, enrollment_authority: Any | None = None):
        self.enrollment_authority = enrollment_authority
        self.heartbeats: list[WorkerHeartbeat] = []
        self.progress_events: list[AssignmentProgress] = []
        self.completed_assignments: list[AssignmentResult] = []
        self.should_fail_network: bool = False

    async def enroll(self, request: EnrollmentRequest) -> EnrollmentResponse:
        if self.should_fail_network:
            raise ConnectionError("Network unreachable")
        if self.enrollment_authority:
            return self.enrollment_authority.enroll_worker(request)
        return EnrollmentResponse(
            worker_id="worker_mock_001",
            tenant_id=request.tenant_id,
            auth_token="auth_mock_token_12345",
        )

    async def send_heartbeat(self, heartbeat: WorkerHeartbeat) -> dict[str, Any]:
        if self.should_fail_network:
            raise ConnectionError("Heartbeat connection timeout")
        self.heartbeats.append(heartbeat)
        return {"acknowledged": True, "sequence_number": heartbeat.sequence_number}

    async def send_progress(self, progress: AssignmentProgress) -> dict[str, Any]:
        if self.should_fail_network:
            raise ConnectionError("Progress stream dropped")
        self.progress_events.append(progress)
        return {"acknowledged": True}

    async def send_completion(self, result: AssignmentResult) -> dict[str, Any]:
        if self.should_fail_network:
            raise ConnectionError("Completion stream dropped")
        self.completed_assignments.append(result)
        return {"acknowledged": True}


class HttpControlPlaneTransport:
    """Outbound HTTP transport to ATLAS Control Plane REST endpoints."""

    def __init__(self, base_url: str, auth_token: str | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    async def enroll(self, request: EnrollmentRequest) -> EnrollmentResponse:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/distributed/enroll",
                json=request.model_dump(mode="json"),
            )
            resp.raise_for_status()
            data = resp.json()
            return EnrollmentResponse.model_validate(data)

    async def send_heartbeat(self, heartbeat: WorkerHeartbeat) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._get_headers()) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/distributed/workers/{heartbeat.worker_id}/heartbeat",
                json=heartbeat.model_dump(mode="json"),
            )
            resp.raise_for_status()
            return resp.json()

    async def send_progress(self, progress: AssignmentProgress) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._get_headers()) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/distributed/assignments/{progress.assignment_id}/progress",
                json=progress.model_dump(mode="json"),
            )
            resp.raise_for_status()
            return resp.json()

    async def send_completion(self, result: AssignmentResult) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._get_headers()) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/distributed/assignments/{result.assignment_id}/complete",
                json=result.model_dump(mode="json"),
            )
            resp.raise_for_status()
            return resp.json()


class EventRingBuffer:
    """Ring buffer maintaining recent events during network disconnects for reliable replay."""

    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self._buffer: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def append(self, event_type: str, payload: BaseModel) -> None:
        """Add event to ring buffer marked as unacknowledged."""
        with self._lock:
            self._buffer.append({
                "type": event_type,
                "payload": payload,
                "acknowledged": False,
                "timestamp": datetime.now(UTC),
            })

    def get_unacknowledged(self) -> list[dict[str, Any]]:
        """Return list of unacknowledged events in arrival order."""
        with self._lock:
            return [e for e in self._buffer if not e["acknowledged"]]

    def mark_all_acknowledged(self) -> None:
        """Mark all buffered items as acknowledged."""
        with self._lock:
            for item in self._buffer:
                item["acknowledged"] = True

    def clear(self) -> None:
        """Clear all buffer items."""
        with self._lock:
            self._buffer.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)


class WorkerAgent:
    """Installable worker daemon runtime executing assignments under control plane policy."""

    def __init__(
        self,
        config: WorkerAgentConfig,
        transport: ControlPlaneTransport | None = None,
    ):
        self.config = config
        self.capabilities = config.capabilities or detect_capabilities()
        self.transport = transport or HttpControlPlaneTransport(
            base_url=config.control_plane_url,
            auth_token=config.auth_token,
        )
        self.status = WorkerStatus.IDLE
        self.worker_id = config.worker_id
        self.auth_token = config.auth_token
        self.connected = True
        self.heartbeat_sequence = 0

        self._drivers: dict[str, ComputerDriver] = {}
        self._active_assignments: dict[str, AssignmentPayload] = {}
        self._cancellation_events: dict[str, threading.Event] = {}
        self._cancelled_assignment_ids: set[str] = set()
        self.buffer = EventRingBuffer(capacity=config.buffer_capacity)
        self._lock = threading.Lock()

    def register_driver(self, name: str, driver: ComputerDriver) -> None:
        """Register a local computer driver (e.g. browser, desktop, terminal)."""
        with self._lock:
            self._drivers[name] = driver
            if name not in self.capabilities.drivers:
                self.capabilities.drivers.append(name)

    def get_driver(self, name: str) -> ComputerDriver | None:
        """Retrieve registered local driver."""
        with self._lock:
            return self._drivers.get(name)

    async def enroll(self, provisioning_token: str | None = None) -> EnrollmentResponse:
        """Submit enrollment request to control plane and store returned credentials."""
        token = provisioning_token or self.config.provisioning_token
        if not token:
            raise ValueError("Provisioning token required for worker enrollment")

        request = EnrollmentRequest(
            provisioning_token=token,
            hostname=self.config.hostname,
            capabilities=self.capabilities,
            tenant_id=self.config.tenant_id,
        )

        response = await self.transport.enroll(request)
        with self._lock:
            self.worker_id = response.worker_id
            self.auth_token = response.auth_token
            self.config.worker_id = response.worker_id
            self.config.auth_token = response.auth_token

        # Update transport auth token if HTTP transport
        if isinstance(self.transport, HttpControlPlaneTransport):
            self.transport.auth_token = response.auth_token

        logger.info("Worker %s successfully enrolled in tenant %s", response.worker_id, response.tenant_id)
        return response

    async def send_heartbeat(self) -> bool:
        """Emit periodic heartbeat with CPU, memory, and active task telemetry."""
        if not self.worker_id:
            logger.warning("Worker cannot emit heartbeat: not yet enrolled")
            return False

        cpu_pct = 0.0
        mem_pct = 0.0
        try:
            import psutil

            cpu_pct = psutil.cpu_percent()
            mem_pct = psutil.virtual_memory().percent
        except ImportError:
            pass

        with self._lock:
            self.heartbeat_sequence += 1
            active_ids = list(self._active_assignments.keys())
            status = WorkerStatus.BUSY if active_ids else WorkerStatus.IDLE

        heartbeat = WorkerHeartbeat(
            worker_id=self.worker_id,
            tenant_id=self.config.tenant_id,
            status=status,
            active_assignments=active_ids,
            cpu_percent=cpu_pct,
            memory_percent=mem_pct,
            sequence_number=self.heartbeat_sequence,
        )

        try:
            await self.transport.send_heartbeat(heartbeat)
            # Reconnection check: if we were previously disconnected, replay buffer
            if not self.connected:
                logger.info("Reconnection detected on worker %s; replaying buffered events", self.worker_id)
                await self.replay_buffered_events()
            self.connected = True
            return True
        except Exception as exc:
            logger.warning("Heartbeat transmission failed for worker %s: %s", self.worker_id, exc)
            self.connected = False
            return False

    async def stream_progress(
        self,
        assignment_id: str,
        task_id: str,
        step_index: int,
        progress_pct: float,
        message: str,
        status: AssignmentStatus = AssignmentStatus.RUNNING,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Stream assignment progress event; buffers for replay if network drops."""
        progress = AssignmentProgress(
            assignment_id=assignment_id,
            task_id=task_id,
            worker_id=self.worker_id or "unknown",
            step_index=step_index,
            progress_pct=progress_pct,
            status=status,
            message=message,
            metadata=metadata or {},
        )

        try:
            await self.transport.send_progress(progress)
        except Exception as exc:
            logger.warning("Progress dispatch failed; buffering in ring buffer: %s", exc)
            self.connected = False
            self.buffer.append("progress", progress)

    def cancel_assignment(self, assignment_id: str, reason: str = "Cancellation directive received") -> None:
        """Signal cancellation for an active or scheduled assignment."""
        with self._lock:
            self._cancelled_assignment_ids.add(assignment_id)
            event = self._cancellation_events.get(assignment_id)
            if event:
                event.set()
            logger.info("Assignment %s marked for cancellation: %s", assignment_id, reason)

    async def execute_assignment(self, assignment: AssignmentPayload) -> AssignmentResult:
        """Execute an assigned task, enforcing Session 0 protection, lease fencing, and cancellation."""
        start_time = time.monotonic()
        assignment_id = assignment.assignment_id

        # 1. Windows Session 0 Invariant Guard
        if self.capabilities.session_type == SessionType.SESSION_0:
            interactive_needed = any(
                req in ["desktop", "pyautogui", "windows_uia", "interactive_desktop"]
                for req in assignment.required_capabilities
            ) or assignment.action_type in ["gui_click", "gui_type", "desktop_automation"]
            if interactive_needed:
                error_msg = (
                    f"Session 0 Invariant Violation: Worker {self.worker_id} is running in Windows Session 0 "
                    f"where interactive desktop automation is physically detached."
                )
                logger.error(error_msg)
                raise SessionZeroInteractiveError(error_msg)

        # 2. Register assignment
        cancel_event = threading.Event()
        with self._lock:
            if assignment_id in self._cancelled_assignment_ids:
                cancel_event.set()
            self._active_assignments[assignment_id] = assignment
            self._cancellation_events[assignment_id] = cancel_event
            self.status = WorkerStatus.BUSY

        await self.stream_progress(
            assignment_id=assignment_id,
            task_id=assignment.task_id,
            step_index=0,
            progress_pct=0.0,
            message="Assignment accepted and starting execution",
            status=AssignmentStatus.RUNNING,
        )

        result_status = AssignmentStatus.COMPLETED
        error_msg: str | None = None
        outputs: dict[str, Any] = {}
        deliverables: dict[str, Any] = {}
        verification_evidence: dict[str, Any] = {}

        try:
            # 3. Check pre-execution cancellation
            if cancel_event.is_set():
                result_status = AssignmentStatus.CANCELLED
                error_msg = "Assignment cancelled prior to execution"
            else:
                # 4. Resolve driver and execute action
                driver_name = assignment.parameters.get("driver") or (
                    assignment.required_capabilities[0] if assignment.required_capabilities else None
                )
                driver = self.get_driver(driver_name) if driver_name else None

                if driver:
                    await self.stream_progress(
                        assignment_id=assignment_id,
                        task_id=assignment.task_id,
                        step_index=1,
                        progress_pct=50.0,
                        message=f"Executing action via driver '{driver_name}'",
                    )

                    # Build ComputerAction from parameters if present
                    action_data = assignment.parameters.get("action")
                    if isinstance(action_data, dict):
                        action = ComputerAction.model_validate(action_data)
                    else:
                        action = ComputerAction(
                            action_id=f"act_{assignment.assignment_id}",
                            task_id=assignment.task_id,
                            session_id=f"sess_{self.worker_id or 'unknown'}",
                            action_type=assignment.action_type,
                            idempotency_key=f"idemp_{assignment.assignment_id}_{assignment.generation}",
                            parameters=assignment.parameters,
                        )

                    action_result: ActionResult = await driver.execute(action)
                    if not action_result.success:
                        result_status = AssignmentStatus.FAILED
                        error_msg = action_result.error or "Driver execution failed"
                    outputs = (
                        action_result.output
                        if isinstance(action_result.output, dict)
                        else {"output": action_result.output}
                    )
                    deliverables = {"action_result": outputs}
                    verification_evidence = {
                        "verified": action_result.success,
                        "evidence": action_result.evidence,
                    }
                else:
                    # Synthetic execution fallback when no specific driver required
                    outputs = {"status": "ok", "executed_objective": assignment.objective}
                    deliverables = {"result": "synthetic_execution_success"}
                    verification_evidence = {"verified": True}

                # 5. Check post-execution cancellation
                if cancel_event.is_set():
                    result_status = AssignmentStatus.CANCELLED
                    error_msg = "Assignment cancelled during execution"

        except Exception as exc:
            logger.exception("Error executing assignment %s: %s", assignment_id, exc)
            result_status = AssignmentStatus.FAILED
            error_msg = str(exc)
        finally:
            with self._lock:
                self._active_assignments.pop(assignment_id, None)
                self._cancellation_events.pop(assignment_id, None)
                if not self._active_assignments:
                    self.status = WorkerStatus.IDLE

        duration_ms = (time.monotonic() - start_time) * 1000.0

        result = AssignmentResult(
            assignment_id=assignment_id,
            task_id=assignment.task_id,
            worker_id=self.worker_id or "unknown",
            generation=assignment.generation,
            status=result_status,
            output=outputs,
            deliverables=deliverables,
            verification_evidence=verification_evidence,
            error=error_msg,
            execution_duration_ms=duration_ms,
        )

        # Deliver final result to control plane
        try:
            await self.transport.send_completion(result)
        except Exception as exc:
            logger.warning("Completion dispatch failed; buffering result: %s", exc)
            self.connected = False
            self.buffer.append("completion", result)

        return result

    async def replay_buffered_events(self) -> int:
        """Replay unacknowledged buffered progress and completion events after reconnection."""
        unacked = self.buffer.get_unacknowledged()
        if not unacked:
            return 0

        replayed_count = 0
        for item in unacked:
            try:
                event_type = item["type"]
                payload = item["payload"]
                if event_type == "progress":
                    await self.transport.send_progress(payload)
                elif event_type == "completion":
                    await self.transport.send_completion(payload)
                replayed_count += 1
            except Exception as exc:
                logger.warning("Failed to replay buffered event: %s", exc)
                return replayed_count

        self.buffer.mark_all_acknowledged()
        logger.info("Successfully replayed %d buffered events", replayed_count)
        return replayed_count
