"""Unit tests for Phase 16.4 Worker Lease Integrity & Fencing Tokens."""

import time

import pytest
from atlas_process.storage import (
    InMemoryProcessStorage,
    SqliteProcessStorage,
)


@pytest.fixture(params=["memory", "sqlite"])
def storage(request, tmp_path):
    if request.param == "memory":
        return InMemoryProcessStorage()
    db_path = str(tmp_path / "test_leases.db")
    s = SqliteProcessStorage(db_path)
    s.initialize()
    return s


def test_lease_acquisition_and_verification(storage):
    """Verify worker lease acquisition produces a valid token and verification succeeds."""
    lease_token, fencing_token = storage.acquire_lease("t_inst_100", "proc_100", "worker_1", 10.0)
    assert lease_token is not None
    assert len(lease_token) >= 16
    assert fencing_token == 1

    # Successful verification
    assert storage.verify_lease("t_inst_100", lease_token, 1) is True

    # Rejection with invalid token
    assert storage.verify_lease("t_inst_100", "invalid_token_xyz", 1) is False

    # Rejection with mismatched fencing token
    assert storage.verify_lease("t_inst_100", lease_token, 99) is False


def test_lease_fencing_token_monotonicity(storage):
    """Verify each lease re-acquisition monotonically increments the fencing token."""
    token1, fence1 = storage.acquire_lease("t_inst_200", "proc_200", "worker_1", 0.5)
    assert fence1 == 1

    # Wait for lease expiration
    time.sleep(0.55)

    token2, fence2 = storage.acquire_lease("t_inst_200", "proc_200", "worker_2", 5.0)
    assert fence2 == 2
    assert token2 != token1

    # Old worker cannot verify old lease token or fencing token
    assert storage.verify_lease("t_inst_200", token1, 1) is False
    # New worker verifies cleanly
    assert storage.verify_lease("t_inst_200", token2, 2) is True


def test_lease_renewal(storage):
    """Verify an active worker can renew its lease without changing the fencing token."""
    token, fence = storage.acquire_lease("t_inst_300", "proc_300", "worker_1", 5.0)

    # Valid renewal
    assert storage.renew_lease("t_inst_300", token, extension_seconds=15.0) is True

    # Verification still passes with same token and fence
    assert storage.verify_lease("t_inst_300", token, fence) is True

    # Attempt renewal with invalid token fails
    assert storage.renew_lease("t_inst_300", "bogus_token", extension_seconds=10.0) is False


def test_lease_release(storage):
    """Verify lease release clears the lease so another worker can immediately acquire."""
    token, fence = storage.acquire_lease("t_inst_400", "proc_400", "worker_1", 60.0)
    assert storage.verify_lease("t_inst_400", token, fence) is True

    # Release lease
    assert storage.release_lease("t_inst_400", token) is True

    # Verification fails after release
    assert storage.verify_lease("t_inst_400", token, fence) is False

    # Another worker can acquire immediately
    token2, fence2 = storage.acquire_lease("t_inst_400", "proc_400", "worker_2", 10.0)
    assert token2 != token
    assert fence2 == fence + 1
