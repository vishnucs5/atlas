"""Unit tests for standalone worker daemon and CLI command workflows."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from atlas_cli.commands.worker import WorkerDaemon
from atlas_cli.main import main
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_storage.sqlite import SQLiteStorage


@pytest.mark.asyncio
async def test_worker_daemon_processing_and_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify WorkerDaemon registers, discovers QUEUED task, executes it, and releases lease."""
    monkeypatch.setenv("ATLAS_HERMETIC_TEST", "1")
    db_file = tmp_path / "worker_test.db"
    storage = SQLiteStorage(str(db_file))
    storage.initialize()

    # Pre-populate a task in QUEUED state
    now = datetime.now(UTC)
    task = Task(
        task_id="task_worker_1",
        objective="Automated worker task execution",
        status=TaskStatus.QUEUED,
        priority=TaskPriority.HIGH,
        created_at=now,
        updated_at=now,
    )
    storage.save_task(task)

    daemon = WorkerDaemon(
        worker_id="test_worker_01",
        db_path=db_file,
        capabilities=["desktop", "browser"],
        heartbeat_interval=0.5,
        poll_interval=0.1,
        max_tasks=1,
        once=True,
    )

    exit_code = await daemon.start()
    assert exit_code == 0
    assert daemon._tasks_processed == 1

    # Verify task completed
    completed_task = storage.get_task("task_worker_1")
    assert completed_task is not None
    assert completed_task.status == TaskStatus.COMPLETED

    # Verify worker was registered and released lease
    worker = storage.get_worker("test_worker_01")
    assert worker is not None
    # On exit, marked disconnected
    assert worker.status.value == "DISCONNECTED"

    storage.close()


def test_cli_task_pause_resume_cancel(tmp_path: Path, monkeypatch) -> None:
    """Verify CLI task pause, resume, and cancel commands."""
    workspace_dir = tmp_path / ".atlas"
    workspace_dir.mkdir(parents=True)
    db_file = workspace_dir / "atlas.db"

    storage = SQLiteStorage(str(db_file))
    storage.initialize()

    now = datetime.now(UTC)
    task = Task(
        task_id="task_cli_ctl",
        objective="Pause and resume control",
        status=TaskStatus.RUNNING,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    storage.save_task(task)
    storage.close()

    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))

    # Test atlas task pause
    pause_res = main(["task", "pause", "task_cli_ctl", "--reason", "Pausing for test"])
    assert pause_res == 0

    storage = SQLiteStorage(str(db_file))
    storage.initialize()
    assert storage.get_task("task_cli_ctl").status == TaskStatus.PAUSED
    storage.close()

    # Test atlas task resume
    resume_res = main(["task", "resume", "task_cli_ctl"])
    assert resume_res == 0

    # Test atlas task cancel
    storage = SQLiteStorage(str(db_file))
    storage.initialize()
    # Reset to RUNNING or PAUSED for cancel
    t = storage.get_task("task_cli_ctl")
    t.status = TaskStatus.RUNNING
    storage.save_task(t)
    storage.close()

    cancel_res = main(["task", "cancel", "task_cli_ctl", "--reason", "Cancelled in test"])
    assert cancel_res == 0

    storage = SQLiteStorage(str(db_file))
    storage.initialize()
    assert storage.get_task("task_cli_ctl").status == TaskStatus.CANCELLED
    storage.close()


def test_cli_approval_commands(tmp_path: Path, monkeypatch) -> None:
    """Verify CLI approval list, grant, and deny subcommands."""
    workspace_dir = tmp_path / ".atlas"
    workspace_dir.mkdir(parents=True)
    db_file = workspace_dir / "atlas.db"

    storage = SQLiteStorage(str(db_file))
    storage.initialize()
    storage.close()

    monkeypatch.setenv("ATLAS_HOME", str(tmp_path))

    # List approvals when empty
    assert main(["approval", "list"]) == 0

    # Test approval grant failure for missing ID
    assert main(["approval", "grant", "missing_req_123"]) == 1

    # Test approval deny failure for missing ID
    assert main(["approval", "deny", "missing_req_123"]) == 1
