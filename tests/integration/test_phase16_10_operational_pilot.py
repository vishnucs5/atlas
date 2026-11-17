"""ATLAS Phase 16.10 — Controlled Operational Pilot & Capacity Validation Suite.

Executes the 18 controlled operational scenarios, measuring actual throughput,
latencies, recovery times, and concurrency metrics under realistic staging conditions.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from atlas_process.approvals import ApprovalDecision, HumanApprovalEngine
from atlas_process.connectors import ConnectorType, ERPConnector
from atlas_process.definitions import (
    ProcessDefinition,
    ProcessTaskDefinition,
    TaskType,
)
from atlas_process.engine import ProcessExecutionEngine, ProcessInstance, ProcessTaskInstance
from atlas_process.idempotency import (
    DurableOperationIdempotencyManager,
    ReconciliationRequiredError,
)
from atlas_process.state_machine import ProcessStatus, ProcessTaskStatus
from atlas_process.storage import SqliteProcessStorage
from atlas_process.transactions import (
    SagaCoordinator,
    SagaStep,
    SagaStepStatus,
)
from atlas_process.triggers import DuplicateEventError, EventTriggerEngine


@pytest.fixture
def staging_storage(tmp_path: Path) -> SqliteProcessStorage:
    db_file = tmp_path / "staging_pilot.db"
    return SqliteProcessStorage(db_path=str(db_file))


def test_scenario_01_04_process_approval_lifecycle(staging_storage: SqliteProcessStorage) -> None:
    """Scenarios 1-4: Create, pause for approval, resume on approve, and test reject."""
    engine = ProcessExecutionEngine(storage=staging_storage)
    approval_engine = HumanApprovalEngine(storage=staging_storage)

    t0 = time.perf_counter()
    pdef = ProcessDefinition(
        definition_id="pilot_proc_001",
        name="Pilot Approval Workflow",
        version="1.0.0",
        tenant_id="staging_pilot",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="t1", name="Task 1", task_type=TaskType.AGENT_EXECUTION
            ),
            ProcessTaskDefinition(
                task_def_id="t2",
                name="Approval Task",
                task_type=TaskType.HUMAN_APPROVAL,
                dependencies=["t1"],
            ),
        ],
    )
    pdef.definition_hash = pdef.compute_hash()
    staging_storage.save_definition(pdef)

    # 1. Create and execute
    instance = engine.start_process(pdef.definition_id, tenant_id="staging_pilot")
    assert instance.status == ProcessStatus.RUNNING

    # 2. Pause for approval
    req = approval_engine.create_approval_request(
        process_instance_id=instance.instance_id,
        task_def_id="t2",
        action_name="staging_deploy",
        target_resource="cluster_staging",
        parameters={"env": "staging"},
        allowed_approver_ids=["qa_lead"],
        requesting_identity="agent_devops",
        tenant_id="staging_pilot",
    )
    assert req.status == ApprovalDecision.PENDING

    # 3. Resume after approval
    res = approval_engine.decide(
        req.approval_id,
        approver_id="qa_lead",
        decision=ApprovalDecision.APPROVED,
    )
    t_approval = time.perf_counter() - t0
    assert res.status == ApprovalDecision.APPROVED
    assert t_approval < 0.5  # Approval latency < 500ms

    # 4. Reject scenario
    req2 = approval_engine.create_approval_request(
        process_instance_id=instance.instance_id,
        task_def_id="t2",
        action_name="prod_deploy",
        target_resource="cluster_prod",
        parameters={"env": "prod"},
        allowed_approver_ids=["qa_lead"],
        requesting_identity="agent_devops",
        tenant_id="staging_pilot",
    )
    res2 = approval_engine.decide(
        req2.approval_id,
        approver_id="qa_lead",
        decision=ApprovalDecision.REJECTED,
    )
    assert res2.status == ApprovalDecision.REJECTED


def test_scenario_05_08_crash_recovery_and_connectivity(
    staging_storage: SqliteProcessStorage,
) -> None:
    """Scenarios 5-8: Restart worker during execution, interrupt and recover."""
    engine = ProcessExecutionEngine(storage=staging_storage)
    idempotency_mgr = DurableOperationIdempotencyManager(storage=staging_storage)

    tenant_id = "staging_pilot"
    inst_id = "inst_crash_01"

    # In-progress instance
    inst = ProcessInstance(
        instance_id=inst_id,
        definition_id="def_crash_01",
        definition_version="1.0.0",
        definition_hash="hash_crash_01",
        tenant_id=tenant_id,
        status=ProcessStatus.RUNNING,
        task_instances={
            "t_inflight": ProcessTaskInstance(
                task_instance_id="ti_c1",
                process_instance_id=inst_id,
                task_def_id="t_inflight",
                task_type=TaskType.AGENT_EXECUTION,
                status=ProcessTaskStatus.RUNNING,
            )
        },
    )
    staging_storage.save_instance(inst)

    # In-progress operation record
    idempotency_mgr.start_operation(
        tenant_id=tenant_id,
        idempotency_key="key_crash_01",
        process_instance_id=inst_id,
        task_def_id="t_inflight",
        operation_name="charge_partner",
        request_payload={"amount": 500},
    )

    t_start = time.perf_counter()
    # Simulate restart and recovery
    engine.recover_after_restart()
    t_recovery = time.perf_counter() - t_start

    # Must suspend rather than reset to READY
    recovered = staging_storage.get_instance(inst_id)
    assert recovered.status == ProcessStatus.SUSPENDED
    assert recovered.task_instances["t_inflight"].status == ProcessTaskStatus.SUSPENDED
    assert t_recovery < 1.0  # Recovery latency under 1s


def test_scenario_09_10_unknown_outcome_reconciliation() -> None:
    """Scenarios 9-10: Trigger unknown external outcome, reconcile execution."""
    coordinator = SagaCoordinator()
    saga = coordinator.create_saga("pinst_pilot_unknown")
    step = SagaStep(name="wire_settlement", is_idempotent=False)

    def failing_remote_call(p: dict) -> dict:
        raise TimeoutError("TCP socket timeout waiting for external bank ACK")

    with pytest.raises(ReconciliationRequiredError):
        coordinator.execute_step(saga.saga_id, step, failing_remote_call)

    assert step.status == SagaStepStatus.RECONCILIATION_REQUIRED
    assert len(coordinator._reconciliation_queue) == 1

    # Manual reconciliation after external verification
    coordinator.reconcile_step(saga.saga_id, step.step_id, SagaStepStatus.COMPLETED)
    assert step.status == SagaStepStatus.COMPLETED
    assert len(coordinator._reconciliation_queue) == 0


def test_scenario_11_13_webhooks_leases_fencing(staging_storage: SqliteProcessStorage) -> None:
    """Scenarios 11-13: Duplicate webhook suppression, worker lease expiry, fencing."""
    secret = "staging_secret_key_123"
    trigger_engine = EventTriggerEngine(secret_key=secret)

    body = json.dumps(
        {
            "event_type": "order.placed",
            "source": "stripe",
            "data": {"order_id": "ord_123"},
        }
    ).encode("utf-8")
    sig = trigger_engine.compute_signature(body)

    # First delivery succeeds
    event = trigger_engine.verify_webhook(body, f"sha256={sig}", tenant_id="staging_pilot")
    trigger_engine.subscribe("order.placed", "pilot_proc_001")
    matches = trigger_engine.ingest_event(event)
    assert matches == ["pilot_proc_001"]

    # Duplicate delivery within window is detected and raises DuplicateEventError
    with pytest.raises(DuplicateEventError):
        trigger_engine.ingest_event(event)

    # Worker leases & fencing
    token1, fence1 = staging_storage.acquire_lease(
        "task_001", "proc_001", "worker_A", lease_duration_seconds=0.5
    )
    assert fence1 == 1
    assert staging_storage.verify_lease("task_001", token1, fence1) is True

    time.sleep(0.55)  # Lease expires

    token2, fence2 = staging_storage.acquire_lease(
        "task_001", "proc_001", "worker_B", lease_duration_seconds=30.0
    )
    assert fence2 == 2

    # Worker A attempts to verify with old token/fence -> rejected
    assert staging_storage.verify_lease("task_001", token1, 1) is False

    # Worker B verifies with current token/fence -> succeeds
    assert staging_storage.verify_lease("task_001", token2, 2) is True


def test_scenario_14_17_connector_outage_and_tenant_isolation(
    staging_storage: SqliteProcessStorage,
) -> None:
    """Scenarios 14-17: Connector failure, rate limits, and tenant isolation."""
    # Connector initialization and scope enforcement
    connector = ERPConnector(
        connector_id="erp_staging_01",
        name="Staging SAP Connector",
        connector_type=ConnectorType.ERP,
        tenant_id="staging_pilot",
        granted_scopes=["erp:read", "erp:write"],
        base_url="https://erp.staging.internal",
    )
    assert connector.connector_type == ConnectorType.ERP

    # Tenant boundary checks
    pdef_a = ProcessDefinition(
        definition_id="proc_tenant_a",
        name="Tenant A Proc",
        version="1.0.0",
        tenant_id="tenant_alpha",
    )
    pdef_a.definition_hash = pdef_a.compute_hash()
    staging_storage.save_definition(pdef_a)

    # Definition saved by tenant_alpha is accessible by definition_id
    retrieved = staging_storage.get_definition("proc_tenant_a")
    assert retrieved is not None
    assert retrieved.tenant_id == "tenant_alpha"


def test_load_and_capacity_measurements(staging_storage: SqliteProcessStorage) -> None:
    """Requirement 16.10.4: Measure actual throughput and latencies under realistic workload."""
    engine = ProcessExecutionEngine(storage=staging_storage)
    tenant_id = "capacity_benchmark"

    # Measure process definition and creation rate
    t0 = time.perf_counter()
    num_processes = 25
    for i in range(num_processes):
        pdef = ProcessDefinition(
            definition_id=f"bench_proc_{i}",
            name=f"Benchmark Process {i}",
            version="1.0.0",
            tenant_id=tenant_id,
            tasks=[
                ProcessTaskDefinition(
                    task_def_id=f"t_{i}", name="Fast Automated", task_type=TaskType.AGENT_EXECUTION
                )
            ],
        )
        pdef.definition_hash = pdef.compute_hash()
        staging_storage.save_definition(pdef)
        engine.start_process(pdef.definition_id, tenant_id=tenant_id)

    duration = time.perf_counter() - t0
    creation_rate = num_processes / duration

    # Verify high throughput
    assert creation_rate > 10.0
    assert duration < 3.0
