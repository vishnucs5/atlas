"""Unit tests for Phase 16.6 Initial Worker Lease Acquisition Race & Monotonic Fencing."""

import concurrent.futures
import pathlib
import tempfile
import time

import pytest
from atlas_process.storage import InMemoryProcessStorage, SqliteProcessStorage


@pytest.fixture(params=["in_memory", "sqlite"])
def storage(request):
    if request.param == "in_memory":
        storage = InMemoryProcessStorage()
        storage.initialize()
        yield storage
    else:
        with tempfile.TemporaryDirectory() as td:
            db_path = pathlib.Path(td) / "test_leases.db"
            storage = SqliteProcessStorage(db_path)
            storage.initialize()
            yield storage


def test_initial_lease_starts_at_fencing_token_one(storage):
    """Test that a brand new task instance starts with fencing_token = 1."""
    lease_token, fencing_token = storage.acquire_lease(
        task_instance_id="task_brand_new_1",
        process_instance_id="proc_1",
        worker_id="worker_alpha",
        lease_duration_seconds=30.0,
    )
    assert fencing_token == 1
    assert lease_token.startswith("lease_")

    # Verify latest lease is valid
    assert storage.verify_lease("task_brand_new_1", lease_token, fencing_token) is True
    # Stale fencing token is rejected
    assert storage.verify_lease("task_brand_new_1", lease_token, 0) is False


def test_concurrent_initial_lease_race_strictly_monotonic(storage):
    """FINDING-16.5-03 regression test:
    Simultaneously execute 10 concurrent workers competing for the initial lease
    on a brand new task. Each worker must obtain a unique, strictly monotonic fencing token.
    """
    task_id = "task_race_initial_01"
    proc_id = "proc_race_01"
    num_workers = 10

    results = []

    def worker_acquire(worker_idx: int):
        worker_id = f"worker_{worker_idx}"
        l_tok, f_tok = storage.acquire_lease(
            task_instance_id=task_id,
            process_instance_id=proc_id,
            worker_id=worker_id,
            lease_duration_seconds=60.0,
        )
        return worker_id, l_tok, f_tok

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_acquire, i) for i in range(num_workers)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    assert len(results) == num_workers
    fencing_tokens = [r[2] for r in results]
    lease_tokens = [r[1] for r in results]

    # All fencing tokens must be unique
    assert len(set(fencing_tokens)) == num_workers
    # Tokens must form the exact sequence {1, 2, ..., num_workers}
    assert sorted(fencing_tokens) == list(range(1, num_workers + 1))
    # All lease tokens must be unique
    assert len(set(lease_tokens)) == num_workers

    # The highest fencing token must be the active lease in storage
    max_fencing = max(fencing_tokens)
    latest_worker_record = next(r for r in results if r[2] == max_fencing)
    assert storage.verify_lease(task_id, latest_worker_record[1], max_fencing) is True

    # Any worker with an older fencing token must fail verification
    for r in results:
        if r[2] < max_fencing:
            assert storage.verify_lease(task_id, r[1], r[2]) is False


def test_lease_expiry_and_reacquisition(storage):
    """Test that after a lease expires, reacquisition increments the fencing token."""
    task_id = "task_exp_01"
    proc_id = "proc_exp_01"

    # Acquire lease with very short duration
    l_tok_1, f_tok_1 = storage.acquire_lease(
        task_instance_id=task_id,
        process_instance_id=proc_id,
        worker_id="worker_1",
        lease_duration_seconds=0.01,
    )
    assert f_tok_1 == 1

    time.sleep(0.02)

    # Reacquire after expiry
    l_tok_2, f_tok_2 = storage.acquire_lease(
        task_instance_id=task_id,
        process_instance_id=proc_id,
        worker_id="worker_2",
        lease_duration_seconds=60.0,
    )
    assert f_tok_2 == 2
    assert l_tok_2 != l_tok_1

    # Worker 1 is now fenced out
    assert storage.verify_lease(task_id, l_tok_1, f_tok_1) is False
    # Worker 2 is authoritative
    assert storage.verify_lease(task_id, l_tok_2, f_tok_2) is True


def test_lease_release_and_subsequent_acquire(storage):
    """Test that releasing a lease allows clean reacquisition with monotonic fencing token."""
    task_id = "task_rel_01"
    proc_id = "proc_rel_01"

    l_tok_1, f_tok_1 = storage.acquire_lease(
        task_instance_id=task_id,
        process_instance_id=proc_id,
        worker_id="worker_1",
        lease_duration_seconds=60.0,
    )
    assert f_tok_1 == 1

    storage.release_lease(task_id, l_tok_1)

    # After release, verification returns False
    assert storage.verify_lease(task_id, l_tok_1, f_tok_1) is False

    # New acquisition gets fencing token 2
    l_tok_2, f_tok_2 = storage.acquire_lease(
        task_instance_id=task_id,
        process_instance_id=proc_id,
        worker_id="worker_2",
        lease_duration_seconds=60.0,
    )
    assert f_tok_2 == 2
    assert storage.verify_lease(task_id, l_tok_2, f_tok_2) is True
