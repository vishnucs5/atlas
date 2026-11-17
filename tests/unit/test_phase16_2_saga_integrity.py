"""Comprehensive tests for Saga compensation integrity in atlas_process.transactions."""

import pytest
from atlas_process.transactions import (
    NonIdempotentBlindRetryError,
    ReconciliationRequiredError,
    SagaCoordinator,
    SagaStatus,
    SagaStep,
    SagaStepStatus,
)


def test_missing_handler_fails_compensation_and_requires_manual_intervention():
    coord = SagaCoordinator()
    saga = coord.create_saga(process_instance_id="p-100")
    step = SagaStep(name="debit_account", forward_payload={"amount": 500})
    step.status = SagaStepStatus.COMPLETED
    saga.steps.append(step)

    # Empty handlers dictionary - missing handler for debit_account
    result = coord.compensate_saga(saga.saga_id, compensation_handlers={})

    assert result is False
    assert saga.status == SagaStatus.MANUAL_INTERVENTION_REQUIRED
    assert step.status == SagaStepStatus.COMPENSATION_UNAVAILABLE
    assert "Missing compensation handler" in (step.error_message or "")
    assert len(step.compensation_history) == 1
    assert step.compensation_history[0]["success"] is False


def test_handler_failure_marks_compensation_failed():
    coord = SagaCoordinator()
    saga = coord.create_saga(process_instance_id="p-101")
    step = SagaStep(name="provision_vm", forward_payload={"vm_id": "vm-99"})
    step.status = SagaStepStatus.COMPLETED
    saga.steps.append(step)

    def failing_handler(payload):
        return False

    result = coord.compensate_saga(saga.saga_id, {"provision_vm": failing_handler})

    assert result is False
    assert saga.status == SagaStatus.PARTIAL_FAILURE
    assert step.status == SagaStepStatus.COMPENSATION_FAILED
    assert step.compensated_at is None


def test_handler_exception_captured_honestly():
    coord = SagaCoordinator()
    saga = coord.create_saga(process_instance_id="p-102")
    step = SagaStep(name="release_license", forward_payload={"key": "xyz"})
    step.status = SagaStepStatus.COMPLETED
    saga.steps.append(step)

    def crashing_handler(payload):
        raise ConnectionResetError("Remote server closed connection")

    result = coord.compensate_saga(saga.saga_id, {"release_license": crashing_handler})

    assert result is False
    assert step.status == SagaStepStatus.COMPENSATION_FAILED
    assert "Remote server closed connection" in (step.error_message or "")


def test_compensation_postcondition_verification_failure():
    coord = SagaCoordinator()
    saga = coord.create_saga(process_instance_id="p-103")
    step = SagaStep(name="delete_storage_bucket", forward_payload={"bucket": "b1"})
    step.status = SagaStepStatus.COMPLETED
    saga.steps.append(step)

    # Handler claims success, but verifier reports failure
    coord.register_compensation_handler(
        "delete_storage_bucket",
        handler=lambda payload: True,
        verification_fn=lambda payload: False,  # Bucket still exists!
    )

    result = coord.compensate_saga(saga.saga_id)

    assert result is False
    assert step.status == SagaStepStatus.COMPENSATION_FAILED
    assert "verification failed" in (step.error_message or "")


def test_compensation_postcondition_verification_success():
    coord = SagaCoordinator()
    saga = coord.create_saga(process_instance_id="p-104")
    step = SagaStep(name="refund_charge", forward_payload={"charge_id": "ch_123"})
    step.status = SagaStepStatus.COMPLETED
    saga.steps.append(step)

    refunded = False

    def refund_handler(payload):
        nonlocal refunded
        refunded = True
        return True

    def refund_verifier(payload):
        return refunded is True

    coord.register_compensation_handler(
        "refund_charge",
        handler=refund_handler,
        verification_fn=refund_verifier,
    )

    result = coord.compensate_saga(saga.saga_id)

    assert result is True
    assert saga.status == SagaStatus.COMPENSATED
    assert step.status == SagaStepStatus.COMPENSATED
    assert step.compensated_at is not None


def test_timeout_enters_reconciliation_required_and_no_blind_retry():
    coord = SagaCoordinator()
    saga = coord.create_saga(process_instance_id="p-105")
    step = SagaStep(name="wire_transfer", forward_payload={"amount": 10000}, is_idempotent=False)

    def timing_out_action(payload):
        raise TimeoutError("Network timeout during bank transfer")

    with pytest.raises(ReconciliationRequiredError):
        coord.execute_step(saga.saga_id, step, timing_out_action)

    assert saga.status == SagaStatus.RECONCILIATION_REQUIRED
    assert step.status == SagaStepStatus.RECONCILIATION_REQUIRED
    assert len(coord._reconciliation_queue) == 1

    # Attempting safe_retry on non-idempotent step must fail
    with pytest.raises(NonIdempotentBlindRetryError):
        coord.safe_retry(step, timing_out_action)


def test_reconciliation_and_manual_resolution():
    coord = SagaCoordinator()
    saga = coord.create_saga(process_instance_id="p-106")
    step = SagaStep(name="charge", forward_payload={"amount": 50})
    step.status = SagaStepStatus.COMPENSATION_UNAVAILABLE
    saga.steps.append(step)
    saga.status = SagaStatus.MANUAL_INTERVENTION_REQUIRED

    # Operator investigates with bank and confirms refund was done manually
    coord.reconcile_step(
        saga.saga_id, step.step_id, SagaStepStatus.COMPENSATED, notes="Confirmed via bank portal"
    )
    assert step.status == SagaStepStatus.COMPENSATED

    coord.manual_resolve(saga.saga_id, resolved_by="admin-jane", notes="Ticket INC-4819 resolved")
    assert saga.status == SagaStatus.COMPENSATED
    assert saga.metadata["manually_resolved_by"] == "admin-jane"
