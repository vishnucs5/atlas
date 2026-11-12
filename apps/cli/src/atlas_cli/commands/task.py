"""Implementation of 'atlas task' subcommands: create, list, and inspect."""

import json
import sys
import uuid
from datetime import UTC, datetime

from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.task import Task, TaskPriority, TaskStatus
from atlas_observability import mask_data, mask_secrets
from atlas_storage import SQLiteStorage

from atlas_cli.config import get_db_path


def _get_storage() -> SQLiteStorage | None:
    """Connect to SQLite storage if initialized, else None."""
    db_path = get_db_path()
    if not db_path.exists():
        print(
            "Error: ATLAS workspace is not initialized. Run 'atlas init' first.",
            file=sys.stderr,
        )
        return None
    storage = SQLiteStorage(str(db_path))
    storage.initialize()
    return storage


def run_task_create(
    objective: str,
    priority: str = "NORMAL",
    metadata_json: str | None = None,
) -> int:
    """Create and persist a new task with an initial TASK_CREATED execution event."""
    try:
        # Validate priority
        try:
            task_priority = TaskPriority(priority.upper())
        except ValueError:
            valid_priorities = ", ".join(p.value for p in TaskPriority)
            print(
                f"Error: Invalid priority '{priority}'. Valid choices: {valid_priorities}",
                file=sys.stderr,
            )
            return 1

        # Parse metadata
        metadata: dict = {}
        if metadata_json:
            try:
                parsed = json.loads(metadata_json)
                if not isinstance(parsed, dict):
                    print("Error: Metadata must be a JSON object.", file=sys.stderr)
                    return 1
                metadata = parsed
            except json.JSONDecodeError as exc:
                print(f"Error: Invalid metadata JSON: {exc}", file=sys.stderr)
                return 1

        storage = _get_storage()
        if storage is None:
            return 1

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)

        task = Task(
            task_id=task_id,
            objective=objective,
            status=TaskStatus.CREATED,
            priority=task_priority,
            created_at=now,
            updated_at=now,
            metadata=metadata,
            schema_version="1.0",
        )
        storage.save_task(task)

        # Record initial TASK_CREATED event
        event = ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            sequence=1,
            event_type=EventType.TASK_CREATED,
            timestamp=now,
            payload={
                "objective": task.objective,
                "priority": task.priority.value,
                "metadata": metadata,
            },
            correlation_id=task_id,
            schema_version="1.0",
        )
        storage.append_event(event)
        storage.close()

        # Display created task details with secrets masked
        safe_obj = mask_secrets(task.objective)
        print(f"Created task: {task.task_id}")
        print(f"Objective:    {safe_obj}")
        print(f"Status:       {task.status.value}")
        print(f"Priority:     {task.priority.value}")
        print(f"Created at:   {task.created_at.isoformat()}")
        if metadata:
            safe_meta = json.dumps(mask_data(metadata))
            print(f"Metadata:     {mask_secrets(safe_meta)}")

        return 0
    except Exception as exc:
        print(f"Error creating task: {exc}", file=sys.stderr)
        return 1


def run_task_list(
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> int:
    """List tasks with optional status filter and pagination."""
    try:
        filter_status = None
        if status_filter:
            try:
                filter_status = TaskStatus(status_filter.upper())
            except ValueError:
                valid_statuses = ", ".join(s.value for s in TaskStatus)
                print(
                    f"Error: Invalid task status '{status_filter}'. Valid choices: {valid_statuses}",
                    file=sys.stderr,
                )
                return 1

        storage = _get_storage()
        if storage is None:
            return 1

        tasks = storage.list_tasks(status=filter_status, limit=limit, offset=offset)
        storage.close()

        if not tasks:
            print("No tasks found.")
            return 0

        # Print header
        header = f"{'TASK ID':<20} {'STATUS':<14} {'PRIORITY':<10} {'CREATED AT':<26} {'OBJECTIVE'}"
        print(header)
        print("-" * len(header))

        for t in tasks:
            safe_obj = mask_secrets(t.objective)
            created_str = t.created_at.isoformat()
            print(
                f"{t.task_id:<20} {t.status.value:<14} {t.priority.value:<10} {created_str:<26} {safe_obj}"
            )

        return 0
    except Exception as exc:
        print(f"Error listing tasks: {exc}", file=sys.stderr)
        return 1


def run_task_inspect(task_id: str) -> int:
    """Inspect a task by ID, displaying full materialized state and execution events."""
    try:
        storage = _get_storage()
        if storage is None:
            return 1

        task = storage.get_task(task_id)
        if task is None:
            storage.close()
            print(f"Error: Task '{task_id}' not found.", file=sys.stderr)
            return 1

        events = storage.get_events(task_id)
        storage.close()

        safe_objective = mask_secrets(task.objective)
        safe_meta = mask_data(task.metadata)

        print("Task Details")
        print("------------")
        print(f"Task ID:        {task.task_id}")
        print(f"Objective:      {safe_objective}")
        print(f"Status:         {task.status.value}")
        print(f"Priority:       {task.priority.value}")
        print(f"Created At:     {task.created_at.isoformat()}")
        print(f"Updated At:     {task.updated_at.isoformat()}")
        print(f"Checkpoint ID:  {task.current_checkpoint_id or 'None'}")
        print(f"Schema Version: {task.schema_version}")
        print(f"Metadata:       {mask_secrets(json.dumps(safe_meta, indent=2))}")
        print()
        print(f"Execution Events ({len(events)}):")
        print("--------------------------------")

        if events:
            for evt in events:
                safe_payload = mask_data(evt.payload)
                payload_str = mask_secrets(json.dumps(safe_payload))
                print(
                    f"  #{evt.sequence} [{evt.timestamp.isoformat()}] {evt.event_type.value} "
                    f"(correlation: {evt.correlation_id})"
                )
                print(f"     Payload: {payload_str}")
        else:
            print("  No execution events recorded.")

        return 0
    except Exception as exc:
        print(f"Error inspecting task: {exc}", file=sys.stderr)
        return 1
