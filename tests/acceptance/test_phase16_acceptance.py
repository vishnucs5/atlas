"""ATLAS Phase 16 Acceptance Test Suite: Autonomous Enterprise Process Execution.

Comprehensive test suite verifying scenarios PROC-01 through PROC-45:
- Process Definitions, DAG Validation, and Versioning (PROC-01 - PROC-05)
- Durable Execution, Parallel/Join Branches, and Fencing (PROC-06 - PROC-16)
- Business Events, Webhook Signatures, and Deduplication (PROC-17 - PROC-19)
- Human Approval, Separation of Duties, and Quorums (PROC-20 - PROC-25)
- Saga Transactions, Compensations, and Reconciliation (PROC-26 - PROC-29)
- Enterprise Connectors, Scopes, and Circuit Breakers (PROC-30 - PROC-33)
- SLA Management, Deadlines, and Escalation (PROC-34 - PROC-35)
- Digital Workforce Allocation and Load Balancing (PROC-36 - PROC-38)
- Process Analytics, Bottlenecks, and Simulation (PROC-39 - PROC-40)
- Federation, Security, Action Firewall, and Core Invariants (PROC-41 - PROC-45)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from atlas_federation import FederationGateway, TrustRelationship
from atlas_process import (
    ActionFirewallBlockedError,
    ApprovalDecision,
    ApprovalExpiredError,
    AssignmentPolicy,
    CircuitBreakerOpenError,
    ConnectorRateLimitExceededError,
    ConnectorScopeViolationError,
    ConnectorType,
    DigitalWorker,
    DuplicateEventError,
    ERPConnector,
    EscalationAction,
    EventTriggerEngine,
    FederatedProcessDelegator,
    ForgedEventError,
    HumanApprovalEngine,
    LeaseExpiredError,
    NonIdempotentBlindRetryError,
    ParameterTamperedError,
    PrivilegeEscalationError,
    ProcessAnalyticsEngine,
    ProcessDefinition,
    ProcessDefinitionValidator,
    ProcessExecutionEngine,
    ProcessSecurityGovernor,
    ProcessSimulationEngine,
    ProcessStatus,
    ProcessTaskDefinition,
    ProcessTaskStatus,
    ReconciliationRequiredError,
    SagaCoordinator,
    SagaStep,
    SagaStepStatus,
    SeparationOfDutiesViolationError,
    SLAManager,
    SLAPolicy,
    StaleWorkerFencingError,
    TaskType,
    TenantIsolationViolationError,
    TicketingConnector,
    UnauthorizedApproverError,
    WorkerKind,
    WorkforceAllocationEngine,
)


@pytest.fixture
def validator() -> ProcessDefinitionValidator:
    return ProcessDefinitionValidator()


@pytest.fixture
def engine() -> ProcessExecutionEngine:
    return ProcessExecutionEngine()


# ---------------------------------------------------------------------------
# PROC-01: Process Definition Validation
# ---------------------------------------------------------------------------
def test_proc01_definition_validation(
    validator: ProcessDefinitionValidator,
) -> None:
    pdef = ProcessDefinition(
        name="InvoiceProcessingProcess",
        version="1.0.0",
        tenant_id="tenant_finance",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="extract_invoice",
                name="Extract Invoice OCR",
                task_type=TaskType.AGENT_EXECUTION,
            ),
            ProcessTaskDefinition(
                task_def_id="approve_payment",
                name="Manager Approval",
                task_type=TaskType.HUMAN_APPROVAL,
                dependencies=["extract_invoice"],
            ),
        ],
    )
    errors = validator.validate(pdef)
    assert len(errors) == 0
    assert pdef.status.value == "VALIDATED"
    assert pdef.definition_hash != ""


# ---------------------------------------------------------------------------
# PROC-02: Invalid Dependency Detection
# ---------------------------------------------------------------------------
def test_proc02_invalid_dependency_detection(
    validator: ProcessDefinitionValidator,
) -> None:
    pdef = ProcessDefinition(
        name="BrokenProcess",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="step1",
                name="Step 1",
                task_type=TaskType.AGENT_EXECUTION,
                dependencies=["nonexistent_step"],
            )
        ],
    )
    errors = validator.validate(pdef)
    assert any("depends on nonexistent task" in err for err in errors)


# ---------------------------------------------------------------------------
# PROC-03: Cyclic Dependency Detection
# ---------------------------------------------------------------------------
def test_proc03_cyclic_dependency_rejection(
    validator: ProcessDefinitionValidator,
) -> None:
    pdef = ProcessDefinition(
        name="CyclicProcess",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="taskA",
                name="Task A",
                task_type=TaskType.AGENT_EXECUTION,
                dependencies=["taskB"],
            ),
            ProcessTaskDefinition(
                task_def_id="taskB",
                name="Task B",
                task_type=TaskType.AGENT_EXECUTION,
                dependencies=["taskA"],
            ),
        ],
    )
    errors = validator.validate(pdef)
    assert any("Cyclic dependency detected" in err for err in errors)


# ---------------------------------------------------------------------------
# PROC-04: Duplicate Task ID Rejection
# ---------------------------------------------------------------------------
def test_proc04_duplicate_task_id_rejection(
    validator: ProcessDefinitionValidator,
) -> None:
    pdef = ProcessDefinition(
        name="DuplicateTasks",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="duplicate_id",
                name="First Step",
                task_type=TaskType.AGENT_EXECUTION,
            ),
            ProcessTaskDefinition(
                task_def_id="duplicate_id",
                name="Second Step",
                task_type=TaskType.AGENT_EXECUTION,
            ),
        ],
    )
    errors = validator.validate(pdef)
    assert any("Duplicate task_def_id" in err for err in errors)


# ---------------------------------------------------------------------------
# PROC-05: Process Version Pinning
# ---------------------------------------------------------------------------
def test_proc05_process_version_pinning(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="OnboardingFlow",
        version="2.3.1",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="welcome",
                name="Send Welcome",
                task_type=TaskType.NOTIFICATION,
            )
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    instance = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_hr")
    assert instance.definition_version == "2.3.1"
    assert instance.definition_hash == pdef.definition_hash


# ---------------------------------------------------------------------------
# PROC-06: Sequential Task Execution
# ---------------------------------------------------------------------------
def test_proc06_sequential_execution(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="SequentialPipeline",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="step1",
                name="Step 1",
                task_type=TaskType.AGENT_EXECUTION,
            ),
            ProcessTaskDefinition(
                task_def_id="step2",
                name="Step 2",
                task_type=TaskType.AGENT_EXECUTION,
                dependencies=["step1"],
            ),
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_01")

    # Initially step1 is READY, step2 is PENDING
    assert inst.task_instances["step1"].status == ProcessTaskStatus.READY
    assert inst.task_instances["step2"].status == ProcessTaskStatus.PENDING

    # Acquire and complete step1
    lease, fencing = engine.acquire_task_lease(inst.instance_id, "step1", "worker_01")
    engine.complete_task(inst.instance_id, "step1", {"data": "done1"}, fencing)

    # Now step2 becomes READY
    assert inst.task_instances["step1"].status == ProcessTaskStatus.COMPLETED
    assert inst.task_instances["step2"].status == ProcessTaskStatus.READY


# ---------------------------------------------------------------------------
# PROC-07: Parallel Branch Execution
# ---------------------------------------------------------------------------
def test_proc07_parallel_execution(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="ParallelBranches",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="root",
                name="Root Task",
                task_type=TaskType.AGENT_EXECUTION,
            ),
            ProcessTaskDefinition(
                task_def_id="branch_a",
                name="Branch A",
                task_type=TaskType.AGENT_EXECUTION,
                dependencies=["root"],
            ),
            ProcessTaskDefinition(
                task_def_id="branch_b",
                name="Branch B",
                task_type=TaskType.AGENT_EXECUTION,
                dependencies=["root"],
            ),
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_01")
    _, fencing = engine.acquire_task_lease(inst.instance_id, "root", "worker_01")
    engine.complete_task(inst.instance_id, "root", {}, fencing)

    # Both parallel branches are now READY
    assert inst.task_instances["branch_a"].status == ProcessTaskStatus.READY
    assert inst.task_instances["branch_b"].status == ProcessTaskStatus.READY


# ---------------------------------------------------------------------------
# PROC-08: Join Synchronization
# ---------------------------------------------------------------------------
def test_proc08_join_synchronization(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="JoinWorkflow",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="branch1",
                name="Branch 1",
                task_type=TaskType.AGENT_EXECUTION,
            ),
            ProcessTaskDefinition(
                task_def_id="branch2",
                name="Branch 2",
                task_type=TaskType.AGENT_EXECUTION,
            ),
            ProcessTaskDefinition(
                task_def_id="join_step",
                name="Join Step",
                task_type=TaskType.GATEWAY_JOIN,
                dependencies=["branch1", "branch2"],
            ),
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_01")

    # Complete branch1 only -> join_step remains PENDING
    _, f1 = engine.acquire_task_lease(inst.instance_id, "branch1", "worker_1")
    engine.complete_task(inst.instance_id, "branch1", {}, f1)
    assert inst.task_instances["join_step"].status == ProcessTaskStatus.PENDING

    # Complete branch2 -> join_step transitions to READY
    _, f2 = engine.acquire_task_lease(inst.instance_id, "branch2", "worker_2")
    engine.complete_task(inst.instance_id, "branch2", {}, f2)
    assert inst.task_instances["join_step"].status == ProcessTaskStatus.READY


# ---------------------------------------------------------------------------
# PROC-09: Conditional Branching
# ---------------------------------------------------------------------------
def test_proc09_conditional_branching(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="ConditionalWorkflow",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="evaluate_risk",
                name="Assess Risk",
                task_type=TaskType.AGENT_EXECUTION,
            ),
            ProcessTaskDefinition(
                task_def_id="high_risk_audit",
                name="Manual Audit",
                task_type=TaskType.HUMAN_APPROVAL,
                dependencies=["evaluate_risk"],
            ),
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(
        definition_id=pdef.definition_id,
        tenant_id="tenant_01",
        initial_variables={"risk_score": 95},
    )
    _, f = engine.acquire_task_lease(inst.instance_id, "evaluate_risk", "worker_1")
    engine.complete_task(inst.instance_id, "evaluate_risk", {"decision": "AUDIT_REQUIRED"}, f)

    assert inst.task_instances["high_risk_audit"].status == ProcessTaskStatus.READY


# ---------------------------------------------------------------------------
# PROC-10: Durable Restart Recovery
# ---------------------------------------------------------------------------
def test_proc10_durable_restart_recovery(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="RecoveryWorkflow",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="t1", name="Task 1", task_type=TaskType.AGENT_EXECUTION
            )
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_01")
    # Acquire lease with 0.0s expiry (immediately expired)
    engine.acquire_task_lease(inst.instance_id, "t1", "worker_crashed", lease_duration_seconds=-1.0)

    # Simulate engine crash and restart
    recovered = engine.recover_after_restart()
    assert recovered == 1
    assert inst.task_instances["t1"].status == ProcessTaskStatus.READY
    assert inst.task_instances["t1"].assigned_to is None


# ---------------------------------------------------------------------------
# PROC-11: Idempotent Process Start
# ---------------------------------------------------------------------------
def test_proc11_idempotent_process_start(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="IdempotentWorkflow",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="t1", name="Task 1", task_type=TaskType.AGENT_EXECUTION
            )
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst1 = engine.start_process(
        definition_id=pdef.definition_id,
        tenant_id="tenant_01",
        idempotency_key="tx_unique_12345",
    )
    inst2 = engine.start_process(
        definition_id=pdef.definition_id,
        tenant_id="tenant_01",
        idempotency_key="tx_unique_12345",
    )

    assert inst1.instance_id == inst2.instance_id


# ---------------------------------------------------------------------------
# PROC-12: Idempotent Task Execution
# ---------------------------------------------------------------------------
def test_proc12_idempotent_task_execution(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="IdemTaskWorkflow",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="t1", name="Task 1", task_type=TaskType.AGENT_EXECUTION
            )
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_01")
    _, fencing = engine.acquire_task_lease(inst.instance_id, "t1", "worker_1")

    engine.complete_task(
        inst.instance_id,
        "t1",
        {"val": 100},
        fencing,
        idempotency_key="task_key_999",
    )
    assert inst.task_instances["t1"].outputs == {"val": 100}

    # Second completion with same key returns cached output without error
    engine.complete_task(
        inst.instance_id,
        "t1",
        {"val": 9999},
        fencing,
        idempotency_key="task_key_999",
    )
    assert inst.task_instances["t1"].outputs == {"val": 100}


# ---------------------------------------------------------------------------
# PROC-13: Worker Lease Acquisition
# ---------------------------------------------------------------------------
def test_proc13_worker_lease_acquisition(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="LeaseTest",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="t1", name="Task 1", task_type=TaskType.AGENT_EXECUTION
            )
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_01")
    lease_token, fencing_token = engine.acquire_task_lease(
        inst.instance_id, "t1", "worker_alpha", lease_duration_seconds=30.0
    )

    assert lease_token.startswith("lease_")
    assert fencing_token == 1
    assert inst.task_instances["t1"].status == ProcessTaskStatus.RUNNING


# ---------------------------------------------------------------------------
# PROC-14: Fencing Against Stale Workers
# ---------------------------------------------------------------------------
def test_proc14_fencing_against_stale_workers(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="FencingTest",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="t1", name="Task 1", task_type=TaskType.AGENT_EXECUTION
            )
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_01")

    # Worker 1 acquires lease (fencing=1)
    _, fencing1 = engine.acquire_task_lease(
        inst.instance_id, "t1", "worker_slow", lease_duration_seconds=-1.0
    )

    # Worker 2 acquires lease after Worker 1 expires (fencing=2)
    _, fencing2 = engine.acquire_task_lease(
        inst.instance_id, "t1", "worker_fast", lease_duration_seconds=30.0
    )

    # Worker 1 tries to commit with stale fencing token (1) -> REJECTED
    with pytest.raises(StaleWorkerFencingError):
        engine.complete_task(inst.instance_id, "t1", {"result": "slow"}, fencing1)

    # Worker 2 commits with active fencing token (2) -> ACCEPTED
    engine.complete_task(inst.instance_id, "t1", {"result": "fast"}, fencing2)
    assert inst.task_instances["t1"].status == ProcessTaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# PROC-15: Worker Lease Expiration
# ---------------------------------------------------------------------------
def test_proc15_worker_lease_expiration(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="ExpireTest",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="t1", name="Task 1", task_type=TaskType.AGENT_EXECUTION
            )
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_01")
    _, fencing = engine.acquire_task_lease(
        inst.instance_id, "t1", "worker_1", lease_duration_seconds=-10.0
    )

    with pytest.raises(LeaseExpiredError):
        engine.complete_task(inst.instance_id, "t1", {}, fencing)


# ---------------------------------------------------------------------------
# PROC-16: Process Cancellation
# ---------------------------------------------------------------------------
def test_proc16_process_cancellation(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    pdef = ProcessDefinition(
        name="CancelFlow",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="t1", name="Task 1", task_type=TaskType.AGENT_EXECUTION
            ),
            ProcessTaskDefinition(
                task_def_id="t2",
                name="Task 2",
                task_type=TaskType.AGENT_EXECUTION,
                dependencies=["t1"],
            ),
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_01")
    engine.cancel_process(inst.instance_id, reason="User requested cancel")

    assert inst.status == ProcessStatus.CANCELLED
    assert inst.task_instances["t1"].status == ProcessTaskStatus.CANCELLED
    assert inst.task_instances["t2"].status == ProcessTaskStatus.CANCELLED


# ---------------------------------------------------------------------------
# PROC-17: Signed Webhook Validation
# ---------------------------------------------------------------------------
def test_proc17_signed_webhook_validation() -> None:
    trigger_engine = EventTriggerEngine(secret_key="my_webhook_secret")
    trigger_engine.subscribe("payment.received", "pdef_invoice_processing_123")

    body = json.dumps(
        {
            "event_type": "payment.received",
            "source": "stripe",
            "data": {"amount": 500, "currency": "USD"},
        }
    ).encode("utf-8")
    signature = trigger_engine.compute_signature(body)

    event = trigger_engine.verify_webhook(body, f"sha256={signature}", tenant_id="tenant_payments")
    matching_defs = trigger_engine.ingest_event(event)

    assert matching_defs == ["pdef_invoice_processing_123"]


# ---------------------------------------------------------------------------
# PROC-18: Forged Webhook Rejection
# ---------------------------------------------------------------------------
def test_proc18_forged_webhook_rejection() -> None:
    trigger_engine = EventTriggerEngine(secret_key="my_webhook_secret")
    body = b'{"event_type": "tampered"}'

    with pytest.raises(ForgedEventError):
        trigger_engine.verify_webhook(body, "sha256=forged_bad_signature", tenant_id="tenant_01")


# ---------------------------------------------------------------------------
# PROC-19: Duplicate Event Suppression
# ---------------------------------------------------------------------------
def test_proc19_duplicate_event_suppression() -> None:
    trigger_engine = EventTriggerEngine(secret_key="secret")
    body = b'{"event_type": "dup_test"}'
    sig = trigger_engine.compute_signature(body)
    event = trigger_engine.verify_webhook(body, sig, tenant_id="tenant_01")

    # Ingest once
    trigger_engine.ingest_event(event)

    # Ingest identical event again -> DuplicateEventError
    with pytest.raises(DuplicateEventError):
        trigger_engine.ingest_event(event)


# ---------------------------------------------------------------------------
# PROC-20: Human Approval Creation
# ---------------------------------------------------------------------------
def test_proc20_human_approval_creation() -> None:
    approval_eng = HumanApprovalEngine()
    req = approval_eng.create_approval_request(
        process_instance_id="pinst_01",
        task_def_id="approve_bonus",
        action_name="payout_bonus",
        target_resource="employee_4402",
        parameters={"bonus_amount": 10000},
        requesting_identity="agent_payroll",
        allowed_approver_ids=["manager_jane"],
    )

    assert req.approval_id.startswith("appr_")
    assert req.parameter_hash != ""
    assert req.status == ApprovalDecision.PENDING


# ---------------------------------------------------------------------------
# PROC-21: Unauthorized Approver Rejection
# ---------------------------------------------------------------------------
def test_proc21_unauthorized_approval_rejection() -> None:
    approval_eng = HumanApprovalEngine()
    req = approval_eng.create_approval_request(
        process_instance_id="pinst_01",
        task_def_id="step_a",
        action_name="action_a",
        target_resource="res_1",
        parameters={"x": 1},
        requesting_identity="agent_1",
        allowed_approver_ids=["authorized_alice"],
    )

    with pytest.raises(UnauthorizedApproverError):
        approval_eng.decide(
            req.approval_id,
            approver_id="intruder_bob",
            decision=ApprovalDecision.APPROVED,
        )


# ---------------------------------------------------------------------------
# PROC-22: Approval Expiration
# ---------------------------------------------------------------------------
def test_proc22_approval_expiration() -> None:
    approval_eng = HumanApprovalEngine()
    req = approval_eng.create_approval_request(
        process_instance_id="pinst_01",
        task_def_id="step_a",
        action_name="action_a",
        target_resource="res_1",
        parameters={"x": 1},
        requesting_identity="agent_1",
        allowed_approver_ids=["alice"],
        duration_seconds=-5.0,  # Expired
    )

    with pytest.raises(ApprovalExpiredError):
        approval_eng.decide(
            req.approval_id,
            approver_id="alice",
            decision=ApprovalDecision.APPROVED,
        )


# ---------------------------------------------------------------------------
# PROC-23: Parameter Tampering Detection
# ---------------------------------------------------------------------------
def test_proc23_approval_parameter_tampering_rejection() -> None:
    approval_eng = HumanApprovalEngine()
    req = approval_eng.create_approval_request(
        process_instance_id="pinst_01",
        task_def_id="wire_transfer",
        action_name="send_wire",
        target_resource="acct_8829",
        parameters={"amount": 5000, "destination": "bank_valid"},
        requesting_identity="agent_finance",
        allowed_approver_ids=["vp_bob"],
    )

    tampered_params = {"amount": 500000, "destination": "bank_attacker"}
    with pytest.raises(ParameterTamperedError):
        approval_eng.decide(
            req.approval_id,
            approver_id="vp_bob",
            decision=ApprovalDecision.APPROVED,
            current_parameters=tampered_params,
        )


# ---------------------------------------------------------------------------
# PROC-24: Separation of Duties (Requestor cannot approve)
# ---------------------------------------------------------------------------
def test_proc24_separation_of_duties_enforcement() -> None:
    approval_eng = HumanApprovalEngine()
    req = approval_eng.create_approval_request(
        process_instance_id="pinst_01",
        task_def_id="sensitive_config",
        action_name="modify_config",
        target_resource="system",
        parameters={"debug": True},
        requesting_identity="developer_dan",
        allowed_approver_ids=["developer_dan", "lead_elena"],
    )

    # Dan requested -> Dan cannot approve!
    with pytest.raises(SeparationOfDutiesViolationError):
        approval_eng.decide(
            req.approval_id,
            approver_id="developer_dan",
            decision=ApprovalDecision.APPROVED,
        )


# ---------------------------------------------------------------------------
# PROC-25: Multi-Person Approval Quorum
# ---------------------------------------------------------------------------
def test_proc25_multi_person_approval_quorum() -> None:
    approval_eng = HumanApprovalEngine()
    req = approval_eng.create_approval_request(
        process_instance_id="pinst_01",
        task_def_id="large_expenditure",
        action_name="authorize_spend",
        target_resource="capital_budget",
        parameters={"cost": 1000000},
        requesting_identity="director_carl",
        allowed_approver_ids=["cfo_claire", "coo_charlie"],
        required_approvals=2,  # Quorum: 2 approvals required
    )

    # First approval -> Status remains PENDING
    approval_eng.decide(
        req.approval_id,
        approver_id="cfo_claire",
        decision=ApprovalDecision.APPROVED,
    )
    assert req.status == ApprovalDecision.PENDING

    # Second approval -> Status transitions to APPROVED
    approval_eng.decide(
        req.approval_id,
        approver_id="coo_charlie",
        decision=ApprovalDecision.APPROVED,
    )
    assert req.status == ApprovalDecision.APPROVED


# ---------------------------------------------------------------------------
# PROC-26: Saga Transaction Execution
# ---------------------------------------------------------------------------
def test_proc26_saga_transaction_execution() -> None:
    coordinator = SagaCoordinator()
    saga = coordinator.create_saga("pinst_travel_1")

    step1 = SagaStep(
        name="book_flight",
        forward_payload={"flight": "UA100"},
        is_idempotent=True,
    )
    step2 = SagaStep(
        name="book_hotel",
        forward_payload={"hotel": "Hilton"},
        is_idempotent=True,
    )

    coordinator.execute_step(saga.saga_id, step1, lambda p: {"ticket": "T123"})
    coordinator.execute_step(saga.saga_id, step2, lambda p: {"reservation": "H456"})

    assert step1.status == SagaStepStatus.COMPLETED
    assert step2.status == SagaStepStatus.COMPLETED


# ---------------------------------------------------------------------------
# PROC-27: Saga Compensation Execution
# ---------------------------------------------------------------------------
def test_proc27_saga_compensation_execution() -> None:
    coordinator = SagaCoordinator()
    saga = coordinator.create_saga("pinst_order_99")

    step1 = SagaStep(name="charge_card", forward_payload={"amount": 250})
    step2 = SagaStep(name="reserve_inventory", forward_payload={"sku": "ITEM_A"})

    coordinator.execute_step(
        saga.saga_id,
        step1,
        lambda p: {"charge_id": "ch_1"},
        compensation_payload={"refund_amount": 250},
    )

    # Step 2 fails
    with pytest.raises(RuntimeError):
        coordinator.execute_step(
            saga.saga_id,
            step2,
            lambda p: (_ for _ in ()).throw(RuntimeError("Out of stock")),
        )

    # Compensations executed
    compensated = coordinator.compensate_saga(
        saga.saga_id,
        compensation_handlers={"charge_card": lambda p: True},
    )
    assert compensated is True
    assert step1.status == SagaStepStatus.COMPENSATED


# ---------------------------------------------------------------------------
# PROC-28: No Blind Retry for Non-Idempotent Operations
# ---------------------------------------------------------------------------
def test_proc28_no_blind_retry_non_idempotent() -> None:
    coordinator = SagaCoordinator()
    step = SagaStep(
        name="send_bank_wire",
        is_idempotent=False,  # Non-idempotent!
    )

    with pytest.raises(NonIdempotentBlindRetryError):
        coordinator.safe_retry(step, lambda p: {})


# ---------------------------------------------------------------------------
# PROC-29: Unknown Outcome Handling & Reconciliation Queue
# ---------------------------------------------------------------------------
def test_proc29_unknown_outcome_reconciliation() -> None:
    coordinator = SagaCoordinator()
    saga = coordinator.create_saga("pinst_banking_1")
    step = SagaStep(name="external_wire_transfer", is_idempotent=False)

    def timing_out_call(p: dict) -> dict:
        raise TimeoutError("Socket timeout waiting for payment gateway")

    with pytest.raises(ReconciliationRequiredError):
        coordinator.execute_step(saga.saga_id, step, timing_out_call)

    assert step.status == SagaStepStatus.RECONCILIATION_REQUIRED
    assert len(coordinator._reconciliation_queue) == 1

    # Reconcile after verifying with payment gateway
    coordinator.reconcile_step(saga.saga_id, step.step_id, SagaStepStatus.COMPLETED)
    assert step.status == SagaStepStatus.COMPLETED
    assert len(coordinator._reconciliation_queue) == 0


# ---------------------------------------------------------------------------
# PROC-30: Connector Least-Privilege Scope Enforcement
# ---------------------------------------------------------------------------
def test_proc30_connector_least_privilege_scope() -> None:
    connector = ERPConnector(
        connector_id="conn_sap_01",
        name="SAP Production",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant_finance",
        granted_scopes=["erp:read_invoice"],  # Lacks create_po scope!
    )

    with pytest.raises(ConnectorScopeViolationError):
        connector.execute(
            action="create_purchase_order",
            required_scope="erp:create_po",
            parameters={"vendor": "Dell", "total_usd": 5000},
        )


# ---------------------------------------------------------------------------
# PROC-31: Connector Rate Limiting
# ---------------------------------------------------------------------------
def test_proc31_connector_rate_limiting() -> None:
    connector = TicketingConnector(
        connector_id="conn_jira",
        name="Jira",
        connector_type=ConnectorType.TICKETING,
        tenant_id="tenant_it",
        granted_scopes=["tickets:write"],
        max_requests_per_minute=2,  # Max 2 req/min
    )

    connector.execute("create_ticket", "tickets:write", {"title": "Issue 1"})
    connector.execute("create_ticket", "tickets:write", {"title": "Issue 2"})

    with pytest.raises(ConnectorRateLimitExceededError):
        connector.execute("create_ticket", "tickets:write", {"title": "Issue 3"})


# ---------------------------------------------------------------------------
# PROC-32: Connector Circuit Breaker
# ---------------------------------------------------------------------------
def test_proc32_connector_circuit_breaker() -> None:
    class FailingConnector(TicketingConnector):
        def _perform_call(self, a, p, k):
            raise ConnectionResetError("Endpoint unreachable")

    connector = FailingConnector(
        connector_id="conn_flaky",
        name="Flaky Endpoint",
        connector_type=ConnectorType.TICKETING,
        tenant_id="tenant_it",
        granted_scopes=["tickets:write"],
        failure_threshold=2,
    )

    # 2 failures trip the circuit
    connector.execute("action", "tickets:write", {})
    connector.execute("action", "tickets:write", {})

    # 3rd call is fast-failed by open circuit
    with pytest.raises(CircuitBreakerOpenError):
        connector.execute("action", "tickets:write", {})


# ---------------------------------------------------------------------------
# PROC-33: Connector Credential Isolation
# ---------------------------------------------------------------------------
def test_proc33_connector_credential_isolation() -> None:
    conn_a = ERPConnector(
        connector_id="conn_a",
        name="ERP Tenant A",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant_A",
        granted_scopes=["erp:read"],
    )
    conn_b = ERPConnector(
        connector_id="conn_b",
        name="ERP Tenant B",
        connector_type=ConnectorType.ERP,
        tenant_id="tenant_B",
        granted_scopes=["erp:read"],
    )

    conn_a.set_credentials({"api_key": "secret_key_tenant_A"})
    conn_b.set_credentials({"api_key": "secret_key_tenant_B"})

    assert conn_a._credentials["api_key"] == "secret_key_tenant_A"
    assert conn_b._credentials["api_key"] == "secret_key_tenant_B"


# ---------------------------------------------------------------------------
# PROC-34: SLA Breach Detection & Escalation
# ---------------------------------------------------------------------------
def test_proc34_sla_breach_detection() -> None:
    manager = SLAManager()
    policy = SLAPolicy(
        name="CriticalTicketSLA",
        target_duration_seconds=60.0,
        escalation_action=EscalationAction.NOTIFY_MANAGER,
    )

    tracker = manager.attach_sla("task_inst_emergency_99", policy, start_time=100.0)

    # Evaluate at time 200 (> 160 deadline)
    escalated = manager.evaluate_slas(current_time=200.0)
    assert len(escalated) == 1
    assert tracker.is_breached is True
    assert tracker.escalation_history[0]["type"] == "BREACH"
    assert tracker.escalation_history[0]["action"] == EscalationAction.NOTIFY_MANAGER.value


# ---------------------------------------------------------------------------
# PROC-35: SLA Warning Threshold
# ---------------------------------------------------------------------------
def test_proc35_sla_warning_threshold() -> None:
    manager = SLAManager()
    policy = SLAPolicy(
        name="StandardSLA",
        target_duration_seconds=100.0,
        warning_threshold_ratio=0.8,  # Alert at 80s
    )

    tracker = manager.attach_sla("proc_inst_42", policy, start_time=0.0)

    # Evaluate at time 85 (warning threshold passed, deadline not breached)
    escalated = manager.evaluate_slas(current_time=85.0)
    assert len(escalated) == 1
    assert tracker.is_warning_sent is True
    assert tracker.is_breached is False


# ---------------------------------------------------------------------------
# PROC-36: Workforce Capability and Skill Matching
# ---------------------------------------------------------------------------
def test_proc36_workforce_skill_matching() -> None:
    workforce = WorkforceAllocationEngine()
    workforce.register_worker(
        DigitalWorker(
            worker_id="agent_python",
            name="Python Coder",
            kind=WorkerKind.AI_AGENT,
            tenant_id="tenant_eng",
            skills=["python", "fastapi"],
        )
    )
    workforce.register_worker(
        DigitalWorker(
            worker_id="agent_doc",
            name="Technical Writer",
            kind=WorkerKind.AI_AGENT,
            tenant_id="tenant_eng",
            skills=["markdown", "docs"],
        )
    )

    selected = workforce.select_worker(required_skills=["python"], tenant_id="tenant_eng")
    assert selected is not None
    assert selected.worker_id == "agent_python"


# ---------------------------------------------------------------------------
# PROC-37: Workforce Workload-Aware Scheduling
# ---------------------------------------------------------------------------
def test_proc37_workforce_workload_aware_scheduling() -> None:
    workforce = WorkforceAllocationEngine()
    workforce.register_worker(
        DigitalWorker(
            worker_id="worker_busy",
            name="Busy Agent",
            kind=WorkerKind.AI_AGENT,
            tenant_id="tenant_ops",
            skills=["triage"],
            current_load=3,
        )
    )
    workforce.register_worker(
        DigitalWorker(
            worker_id="worker_free",
            name="Free Agent",
            kind=WorkerKind.AI_AGENT,
            tenant_id="tenant_ops",
            skills=["triage"],
            current_load=0,
        )
    )

    selected = workforce.select_worker(required_skills=["triage"], tenant_id="tenant_ops")
    assert selected is not None
    assert selected.worker_id == "worker_free"


# ---------------------------------------------------------------------------
# PROC-38: Human vs. Agent Routing Policy
# ---------------------------------------------------------------------------
def test_proc38_workforce_human_vs_agent_policy() -> None:
    workforce = WorkforceAllocationEngine()
    workforce.register_worker(
        DigitalWorker(
            worker_id="agent_ai",
            name="AI Auditor",
            kind=WorkerKind.AI_AGENT,
            tenant_id="tenant_compliance",
            skills=["audit"],
        )
    )
    workforce.register_worker(
        DigitalWorker(
            worker_id="human_operator",
            name="Human Auditor",
            kind=WorkerKind.HUMAN_OPERATOR,
            tenant_id="tenant_compliance",
            skills=["audit"],
        )
    )

    # Policy HUMAN_ONLY
    human = workforce.select_worker(
        required_skills=["audit"],
        tenant_id="tenant_compliance",
        policy=AssignmentPolicy.HUMAN_ONLY,
    )
    assert human is not None
    assert human.worker_id == "human_operator"

    # Policy AGENT_ONLY
    agent = workforce.select_worker(
        required_skills=["audit"],
        tenant_id="tenant_compliance",
        policy=AssignmentPolicy.AGENT_ONLY,
    )
    assert agent is not None
    assert agent.worker_id == "agent_ai"


# ---------------------------------------------------------------------------
# PROC-39: Process Analytics & Bottleneck Identification
# ---------------------------------------------------------------------------
def test_proc39_process_analytics_summary(
    engine: ProcessExecutionEngine, validator: ProcessDefinitionValidator
) -> None:
    analytics = ProcessAnalyticsEngine()

    pdef = ProcessDefinition(
        name="ProcAnalyticsTest",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="fast_step",
                name="Fast",
                task_type=TaskType.AGENT_EXECUTION,
            ),
            ProcessTaskDefinition(
                task_def_id="slow_bottleneck",
                name="Slow",
                task_type=TaskType.AGENT_EXECUTION,
                dependencies=["fast_step"],
            ),
        ],
    )
    validator.validate(pdef)
    engine.register_definition(pdef)

    inst = engine.start_process(definition_id=pdef.definition_id, tenant_id="tenant_analytics")

    # Step 1: 1s duration
    inst.task_instances["fast_step"].started_at = 100.0
    inst.task_instances["fast_step"].completed_at = 101.0
    inst.task_instances["fast_step"].status = ProcessTaskStatus.COMPLETED

    # Step 2: 20s duration
    inst.task_instances["slow_bottleneck"].started_at = 101.0
    inst.task_instances["slow_bottleneck"].completed_at = 121.0
    inst.task_instances["slow_bottleneck"].status = ProcessTaskStatus.COMPLETED

    inst.status = ProcessStatus.COMPLETED
    inst.created_at = 100.0
    inst.completed_at = 121.0

    analytics.record_completed_process(inst)
    summary = analytics.compute_summary("tenant_analytics")

    assert summary.total_instances == 1
    assert summary.completed_instances == 1
    assert summary.avg_cycle_time_seconds == 21.0
    assert summary.bottleneck_task_id == "slow_bottleneck"


# ---------------------------------------------------------------------------
# PROC-40: Process Simulation with Zero Side-Effects
# ---------------------------------------------------------------------------
def test_proc40_simulation_zero_side_effects(
    validator: ProcessDefinitionValidator,
) -> None:
    sim_engine = ProcessSimulationEngine()
    pdef = ProcessDefinition(
        name="SimulatedSupplyChain",
        tasks=[
            ProcessTaskDefinition(
                task_def_id="step_a",
                name="A",
                task_type=TaskType.AGENT_EXECUTION,
            ),
            ProcessTaskDefinition(
                task_def_id="step_b",
                name="B",
                task_type=TaskType.AGENT_EXECUTION,
                dependencies=["step_a"],
            ),
        ],
    )
    validator.validate(pdef)

    result = sim_engine.simulate(
        definition=pdef,
        iterations=30,
        task_duration_distributions={
            "step_a": (5.0, 1.0),
            "step_b": (15.0, 2.0),
        },
    )

    assert result.iterations == 30
    assert result.avg_simulated_duration_seconds > 10.0
    assert result.side_effects_triggered == 0  # Invariant: 0 side effects!
    assert result.simulated_bottleneck_task_id == "step_b"


# ---------------------------------------------------------------------------
# PROC-41: Federated Process Task Delegation
# ---------------------------------------------------------------------------
def test_proc41_federated_task_delegation() -> None:
    gateway_alpha = FederationGateway("org_alpha", "inst_alpha_01")
    gateway_beta = FederationGateway("org_beta", "inst_beta_01")

    # Mutual enrollment
    gateway_alpha.enroll_peer("org_beta", TrustRelationship.TRUSTED)
    gateway_beta.enroll_peer("org_alpha", TrustRelationship.TRUSTED)

    delegator = FederatedProcessDelegator(gateway_alpha)
    proposal_id = delegator.delegate_business_step(
        target_org_id="org_beta",
        target_installation_id="inst_beta_01",
        objective="Cross-organization invoice clearance",
        parameters={"invoice_id": "INV-9901", "amount": 15000},
    )

    assert proposal_id.startswith("prop_")


# ---------------------------------------------------------------------------
# PROC-42: Cross-Tenant Isolation Enforcement
# ---------------------------------------------------------------------------
def test_proc42_cross_tenant_isolation() -> None:
    sec = ProcessSecurityGovernor()

    # Access across differing tenants is blocked
    with pytest.raises(TenantIsolationViolationError):
        sec.check_tenant_boundary(
            requesting_tenant_id="tenant_attacker",
            target_tenant_id="tenant_victim_enterprise",
        )


# ---------------------------------------------------------------------------
# PROC-43: Workflow Privilege Escalation Rejection
# ---------------------------------------------------------------------------
def test_proc43_workflow_privilege_escalation_rejection() -> None:
    sec = ProcessSecurityGovernor()

    # Attempting to disable firewall or self-elevate is blocked
    with pytest.raises(PrivilegeEscalationError):
        sec.evaluate_task_action(
            action_name="firewall:disable",
            parameters={"bypass": True},
            tenant_id="tenant_01",
        )


# ---------------------------------------------------------------------------
# PROC-44: Action Firewall Integration
# ---------------------------------------------------------------------------
def test_proc44_action_firewall_integration() -> None:
    sec = ProcessSecurityGovernor()

    # Destructive commands are blocked by Action Firewall
    with pytest.raises(ActionFirewallBlockedError):
        sec.evaluate_task_action(
            action_name="bash_command",
            parameters={"command": "rm -rf /; drop table users;"},
            tenant_id="tenant_01",
        )


# ---------------------------------------------------------------------------
# PROC-45: Monorepo Core Zero-Dependency Invariant
# ---------------------------------------------------------------------------
def test_proc45_monorepo_core_zero_dependency_invariant() -> None:
    core_toml_path = (
        Path(__file__).resolve().parents[2] / "packages" / "atlas-core" / "pyproject.toml"
    )
    assert core_toml_path.exists(), f"Path {core_toml_path} not found"

    content = core_toml_path.read_text(encoding="utf-8")
    for forbidden in [
        "kubernetes",
        "playwright",
        "psycopg",
        "asyncpg",
        "fastapi",
        "docker",
        "torch",
        "sklearn",
    ]:
        assert forbidden not in content.lower(), (
            f"Constitutional Invariant 3 Violated: Forbidden dependency '{forbidden}' detected in atlas-core!"
        )

    # Verify atlas-process registered in root pyproject.toml
    root_toml = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert "packages/atlas-process" in root_toml
