"""Independent Performance and Scalability Audit Tests for Phase 10.

Measures:
- Audit ledger cryptographic hash-chain throughput at scale (1,000 records).
- Hash chain integrity verification latency.
- Rate limiter sliding window log throughput and latency.
- Concurrent multi-threaded acquisition latency.
"""

import concurrent.futures
import time

from atlas_enterprise import (
    EnterpriseAuditLedger,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
)
from atlas_enterprise.integrations import TokenBucketRateLimiter


def test_audit_perf_01_hash_chain_throughput_and_verification():
    """Measure throughput and latency of appending and verifying 1,000 audit records."""
    org_mgr = EnterpriseOrganizationManager()
    iam = EnterpriseIAMEngine(org_mgr)
    audit = EnterpriseAuditLedger(org_mgr, iam)

    org, owner, _ = org_mgr.create_organization(
        name="PerfCorp", slug="perfcorp", owner_email="p@perf.com", owner_name="Perf"
    )

    count = 1000
    start_time = time.perf_counter()
    for i in range(count):
        audit.append_entry(
            org_id=org.org_id,
            event_type="PERF_EVENT",
            actor_id=owner.user_id,
            actor_type="USER",
            action=f"action.test_{i}",
            details={"index": i, "meta": "benchmark_payload"},
        )
    append_duration = time.perf_counter() - start_time
    append_ops_per_sec = count / append_duration
    assert append_ops_per_sec > 0

    # Verify chain
    verify_start = time.perf_counter()
    is_intact, broken_seq, _ = audit.verify_chain_integrity(org.org_id)
    verify_duration = time.perf_counter() - verify_start

    assert is_intact is True
    assert broken_seq is None
    assert append_duration < 5.0, f"Appending {count} records took {append_duration:.2f}s (> 5s)"
    assert verify_duration < 2.0, f"Verifying {count} records took {verify_duration:.2f}s (> 2s)"


def test_audit_perf_02_rate_limiter_concurrency_and_contention():
    """Test sliding window rate limiter under high concurrent thread load."""
    rpm = 500
    limiter = TokenBucketRateLimiter(rpm=rpm)

    total_requests = 1000
    acquired_count = 0
    denied_count = 0

    def worker_request():
        return limiter.acquire()

    start_time = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(worker_request) for _ in range(total_requests)]
        for f in concurrent.futures.as_completed(futures):
            if f.result():
                acquired_count += 1
            else:
                denied_count += 1
    duration = time.perf_counter() - start_time

    assert acquired_count == rpm, f"Expected exactly {rpm} acquired, got {acquired_count}"
    assert denied_count == total_requests - rpm
    assert duration < 2.0, f"Concurrent rate limit execution took {duration:.2f}s (> 2s)"
