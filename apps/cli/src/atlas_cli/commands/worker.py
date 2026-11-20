"""Worker daemon command for background distributed ATLAS task execution."""

import asyncio
import logging
import os
import platform
import signal
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_agent.runtime import ProductionRuntime
from atlas_core.contracts.session import Session, SessionStatus
from atlas_core.contracts.task import TaskStatus
from atlas_storage.sqlite import SQLiteStorage

from atlas_cli.config import get_db_path

logger = logging.getLogger("atlas.worker")


class WorkerDaemon:
    """Autonomous background worker executing assigned tasks with lease fencing."""

    def __init__(
        self,
        worker_id: str | None = None,
        db_path: str | Path | None = None,
        capabilities: list[str] | None = None,
        heartbeat_interval: float = 5.0,
        poll_interval: float = 1.0,
        max_tasks: int = 0,
        once: bool = False,
    ) -> None:
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.db_path = str(db_path or get_db_path())
        self.capabilities = capabilities or ["desktop", "browser"]
        self.heartbeat_interval = heartbeat_interval
        self.poll_interval = poll_interval
        self.max_tasks = max_tasks
        self.once = once
        self.hostname = platform.node() or "localhost"

        self.storage: Any = None
        self.runtime: ProductionRuntime | None = None
        self._running = False
        self._tasks_processed = 0

    async def start(self) -> int:
        """Start worker lifecycle: register node, initiate heartbeat, and enter poll loop."""
        print(f"[*] Starting ATLAS Worker Daemon '{self.worker_id}' on '{self.hostname}'")
        database_url = os.environ.get("ATLAS_DATABASE_URL")
        database_target = database_url.rsplit("@", maxsplit=1)[-1] if database_url else self.db_path
        print(f"[*] Database: {database_target}")
        print(f"[*] Capabilities: {', '.join(self.capabilities)}")

        # Initialize storage & runtime
        if database_url and database_url.startswith(("postgresql://", "postgres://")):
            from atlas_storage.postgres import PostgresStorage

            self.storage = PostgresStorage(database_url)
        else:
            self.storage = SQLiteStorage(self.db_path)
        self.storage.initialize()

        if sys.platform == "win32" and "desktop" in self.capabilities:
            from atlas_browser.desktop import DesktopDriver

            is_interactive, msg = DesktopDriver.validate_interactive_session()
            if not is_interactive:
                print(f"[!] WARNING: {msg}")
                logger.warning(msg)
            else:
                print(f"[+] {msg}")

        self.runtime = ProductionRuntime(storage=self.storage)
        await self.runtime.initialize()

        # Register worker in fleet registry
        self.runtime.worker_registry.register(
            worker_id=self.worker_id,
            hostname=self.hostname,
            capabilities=self.capabilities,
            metadata={"pid": os.getpid(), "start_time": datetime.now(UTC).isoformat()},
        )
        print(f"[+] Worker '{self.worker_id}' registered successfully (Status: IDLE)")

        self._running = True
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            await self._work_loop()
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            await self._cleanup()

        print(
            f"[*] Worker '{self.worker_id}' exited. Total tasks processed: {self._tasks_processed}"
        )
        return 0

    async def _heartbeat_loop(self) -> None:
        """Periodic background task emitting worker heartbeat signals."""
        while self._running:
            try:
                if self.runtime:
                    self.runtime.worker_registry.heartbeat(self.worker_id)
            except Exception as exc:
                logger.warning("Heartbeat failed: %s", exc)
            await asyncio.sleep(self.heartbeat_interval)

    async def _work_loop(self) -> None:
        """Main dispatch loop polling for QUEUED tasks matching capabilities."""
        while self._running:
            task = self._find_queued_task()
            if task:
                print(f"[>] Discovered eligible task '{task.task_id}': {task.objective}")
                try:
                    await self._process_task(task.task_id)
                    self._tasks_processed += 1
                except Exception as exc:
                    print(f"[!] Error processing task '{task.task_id}': {exc}", file=sys.stderr)

                if self.once or (self.max_tasks > 0 and self._tasks_processed >= self.max_tasks):
                    break
            else:
                if self.once:
                    print("[*] No queued tasks available (--once mode). Exiting.")
                    break
                await asyncio.sleep(self.poll_interval)

    def _find_queued_task(self) -> Any:
        """Find the oldest task in QUEUED status."""
        if not self.storage:
            return None
        all_tasks = self.storage.list_tasks(limit=100)
        # Filter for QUEUED
        queued = [t for t in all_tasks if t.status == TaskStatus.QUEUED]
        return queued[0] if queued else None

    async def _process_task(self, task_id: str) -> None:
        """Acquire lease, transition to PLANNING -> READY -> RUNNING, and execute agent loop."""
        if not self.runtime or not self.storage:
            return

        # 1. Acquire task lease via scheduler
        lease = self.runtime.lease_mgr.acquire_lease(
            task_id=task_id,
            worker_id=self.worker_id,
            ttl_seconds=120.0,
        )
        self.runtime.worker_registry.mark_busy(self.worker_id, current_task_id=task_id)
        print(
            f"[+] Acquired lease '{lease.lease_id}' for task '{task_id}' (Gen: {lease.generation})"
        )

        task = self.storage.get_task(task_id)
        if not task:
            return

        try:
            # 2. QUEUED -> PLANNING
            await self.runtime._transition_task(
                task, TaskStatus.PLANNING, reason=f"Worker '{self.worker_id}' planning task"
            )
            plan = self.runtime.planner.create_plan(task_id=task.task_id, goal=task.objective)
            task.metadata["plan"] = plan.model_dump()
            self.storage.save_task(task)

            # 3. PLANNING -> READY
            await self.runtime._transition_task(
                task, TaskStatus.READY, reason="Execution plan synthesized"
            )

            # 4. Create Session & READY -> RUNNING
            now = datetime.now(UTC)
            session = Session(
                session_id=f"sess_w_{uuid.uuid4().hex[:8]}",
                task_id=task.task_id,
                status=SessionStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            await self.runtime._transition_task(
                task,
                TaskStatus.RUNNING,
                session_id=session.session_id,
                reason="Worker started execution",
            )

            # 5. Execute Agent Loop
            task = await self.runtime.loop.run(task, session)
            self.storage.save_task(task)
            print(f"[✔] Task '{task.task_id}' finished in status: {task.status.value}")

        finally:
            # 6. Release lease and restore worker to IDLE
            try:
                self.runtime.lease_mgr.release_lease(lease.lease_id, self.worker_id)
            except Exception as exc:
                logger.error(
                    "Failed to release worker lease",
                    extra={
                        "lease_id": lease.lease_id,
                        "worker_id": self.worker_id,
                        "error": str(exc),
                    },
                )
            self.runtime.worker_registry.mark_idle(self.worker_id)

    async def _cleanup(self) -> None:
        """Mark worker disconnected and shut down runtime."""
        if self.runtime:
            try:
                self.runtime.worker_registry.mark_disconnected(self.worker_id)
            except Exception as exc:
                logger.error(
                    "Failed to mark worker disconnected",
                    extra={"worker_id": self.worker_id, "error": str(exc)},
                )
            await self.runtime.shutdown()


def run_worker_daemon(
    worker_id: str | None = None,
    db_path: str | Path | None = None,
    capabilities: list[str] | None = None,
    heartbeat_interval: float = 5.0,
    poll_interval: float = 1.0,
    max_tasks: int = 0,
    once: bool = False,
) -> int:
    """Synchronous entrypoint for starting the worker daemon."""
    daemon = WorkerDaemon(
        worker_id=worker_id,
        db_path=db_path,
        capabilities=capabilities,
        heartbeat_interval=heartbeat_interval,
        poll_interval=poll_interval,
        max_tasks=max_tasks,
        once=once,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal(*_: Any) -> None:
        print("\n[!] Shutdown signal received. Exiting worker gracefully...")
        daemon._running = False

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except (ValueError, AttributeError):
        pass

    try:
        return loop.run_until_complete(daemon.start())
    finally:
        loop.close()
