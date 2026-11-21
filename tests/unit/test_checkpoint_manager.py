"""Unit tests for CheckpointManager: sealing, verification, secret redaction, and rollback."""

from pathlib import Path

import pytest
from atlas_coordination.checkpoint_manager import CheckpointManager, redact_secrets
from atlas_core.contracts.event import EventType
from atlas_core.contracts.task import TaskStatus
from atlas_storage.interfaces import CorruptedCheckpointError
from atlas_storage.sqlite import SQLiteStorage


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStorage:
    db = tmp_path / "test_chk_mgr.db"
    s = SQLiteStorage(str(db))
    s.initialize()
    return s


def test_redact_secrets_recursive() -> None:
    data = {
        "user": "alice",
        "password": "super-secret-password-123",
        "nested": {
            "api_key": "sk-" + "1234567890abcdef",
            "normal_field": "hello world",
            "headers": ["normal", "bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"],
        },
    }
    redacted = redact_secrets(data)
    assert redacted["user"] == "alice"
    assert redacted["password"] == "***REDACTED***"
    assert redacted["nested"]["api_key"] == "***REDACTED***"
    assert redacted["nested"]["normal_field"] == "hello world"
    assert "eyJhbGci" not in redacted["nested"]["headers"][1]
    assert "Bearer ***REDACTED***" in redacted["nested"]["headers"][1]


def test_create_and_verify_checkpoint(store: SQLiteStorage) -> None:
    mgr = CheckpointManager(checkpoint_store=store, event_store=store)

    chk = mgr.create_checkpoint(
        task_id="task_mgr_1",
        state=TaskStatus.RUNNING,
        sequence=1,
        worker_id="worker_alpha",
        lease_generation=1,
        state_snapshot={"url": "https://example.com", "token": "secret_abc"},
        completed_action_ids=["act_0"],
    )

    assert chk.checkpoint_id.startswith("chk_")
    assert chk.checkpoint_hash is not None
    assert chk.verify_hash() is True

    # Confirm secrets were redacted in stored checkpoint
    loaded = mgr.get_checkpoint(chk.checkpoint_id, verify=True)
    assert loaded is not None
    assert loaded.state_snapshot["token"] == "***REDACTED***"

    # Confirm event was appended
    events = store.get_events("task_mgr_1")
    assert len(events) == 1
    assert events[0].event_type == EventType.CHECKPOINT_CREATED
    assert events[0].payload["checkpoint_id"] == chk.checkpoint_id


def test_corrupted_checkpoint_detection_and_rollback(store: SQLiteStorage) -> None:
    mgr = CheckpointManager(checkpoint_store=store, event_store=store)

    # Checkpoint 1 (valid)
    chk1 = mgr.create_checkpoint(
        task_id="task_rollback_1",
        state=TaskStatus.RUNNING,
        sequence=1,
        state_snapshot={"step": 1},
    )

    # Checkpoint 2 (valid initially)
    chk2 = mgr.create_checkpoint(
        task_id="task_rollback_1",
        state=TaskStatus.RUNNING,
        sequence=2,
        state_snapshot={"step": 2},
    )

    # Intentionally tamper with chk2 in database directly to simulate disk corruption or tampering
    with store._lock:
        conn = store._get_connection()
        conn.execute(
            "UPDATE checkpoints SET state = 'TAMPERED_STATE' WHERE checkpoint_id = ?;",
            (chk2.checkpoint_id,),
        )
        conn.commit()

    # get_checkpoint on chk2 with verify=True must raise CorruptedCheckpointError
    with pytest.raises(CorruptedCheckpointError):
        mgr.get_checkpoint(chk2.checkpoint_id, verify=True)

    # Rollback must bypass corrupted chk2 and return chk1
    rolled_back = mgr.rollback_to_last_valid("task_rollback_1")
    assert rolled_back.checkpoint_id == chk1.checkpoint_id
    assert rolled_back.sequence == 1
    assert rolled_back.verify_hash() is True
