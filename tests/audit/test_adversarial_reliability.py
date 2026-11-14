"""Independent Reliability and Crash Recovery Audit Tests for Phase 10.

Tests:
- Concurrency under multithreaded budget deductions (preventing overspend race conditions).
- Unhandled exceptions on missing entities (e.g. NoneType dereference).
- Non-serializable details in audit records leading to json.dumps TypeError.
- In-memory ephemeral state loss simulation (process restart scenario).
"""

import concurrent.futures
from datetime import UTC, datetime

import pytest
from atlas_enterprise import (
    BudgetCapExceededError,
    EnterpriseCostManager,
    EnterpriseIAMEngine,
    EnterpriseOrganizationManager,
    compute_record_hash,
)


def test_audit_rel_01_concurrent_budget_deductions_prevent_overspend():
    """Verify that concurrent threads deducting costs do not breach the hard cap due to race conditions."""
    org_mgr = EnterpriseOrganizationManager()
    iam = EnterpriseIAMEngine(org_mgr)
    cost = EnterpriseCostManager(org_mgr, iam)

    org, owner, _ = org_mgr.create_organization(
        name="CapCorp", slug="capcorp", owner_email="c@cap.com", owner_name="Owner"
    )
    dept = org_mgr.create_department(org.org_id, "RaceDept", "racedept")

    # Hard cap of $10.00
    budget = cost.set_department_budget(
        caller_user_id=owner.user_id,
        org_id=org.org_id,
        department_id=dept.department_id,
        allocated_usd=10.0,
        hard_cap_enabled=True,
    )
    assert budget.allocated_usd == 10.0

    # 20 workers each trying to spend $1.00
    # Total attempted = $20.00. Exactly 10 should succeed, 10 should raise BudgetCapExceededError.
    def worker_spend(idx: int):
        try:
            cost.record_usage(
                org_id=org.org_id,
                task_id=f"task_{idx}",
                model_name="default",
                prompt_tokens=250_000,  # 250 * 0.002 = $0.50
                completion_tokens=83_333,  # 83.333 * 0.006 = $0.50 -> Total $1.00
                compute_duration_ms=0,
                department_id=dept.department_id,
            )
            return True
        except BudgetCapExceededError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker_spend, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    success_count = sum(1 for r in results if r is True)
    failure_count = sum(1 for r in results if r is False)

    # Spent must never exceed $10.00
    current_budget = cost.get_department_budget(org.org_id, dept.department_id)
    assert current_budget.spent_usd <= 10.0
    assert success_count == 10
    assert failure_count == 10


def test_audit_rel_02_attribute_error_on_nonexistent_org_in_iam():
    """Verify that calling create_session with non-existent org_id raises OrganizationNotFoundError."""
    from atlas_enterprise import OrganizationNotFoundError

    org_mgr = EnterpriseOrganizationManager()
    iam = EnterpriseIAMEngine(org_mgr)

    user = org_mgr.provision_user(
        user_id="usr_test_fail", email="t@fail.com", full_name="Fail Test"
    )

    # Calling with non-existent org_id cleanly raises OrganizationNotFoundError
    with pytest.raises(OrganizationNotFoundError, match="not found"):
        iam.create_session(
            user_id=user.user_id,
            org_id="non_existent_org_id",
        )


def test_audit_rel_03_non_serializable_details_in_audit_record():
    """Verify that non-JSON-serializable objects in details are handled cleanly via default=str without crashing."""
    # Passing a set or custom object in details dictionary
    non_serializable_details = {"allowed_set": {1, 2, 3}, "object": object()}

    h = compute_record_hash(
        sequence=1,
        org_id="org_test",
        department_id=None,
        event_type="TEST",
        actor_id="actor_1",
        actor_type="USER",
        action="test.action",
        target_resource_id=None,
        details=non_serializable_details,
        timestamp=datetime.now(UTC),
        previous_hash="0" * 64,
    )
    assert len(h) == 64
    assert isinstance(h, str)


def test_audit_rel_04_ephemeral_state_loss_on_system_restart(tmp_path):
    """Verify that EnterpriseStorage persists state across component re-instantiations."""
    from atlas_enterprise import EnterpriseStorage

    db_file = tmp_path / "enterprise_persist.db"
    storage = EnterpriseStorage(db_path=str(db_file))

    # Initial state with persistence
    org_mgr_1 = EnterpriseOrganizationManager(storage=storage)
    org, _, _ = org_mgr_1.create_organization(
        name="Durable Corp", slug="durable", owner_email="d@durable.com", owner_name="Owner"
    )
    assert org_mgr_1.get_organization(org.org_id) is not None

    # Simulate process restart by instantiating new storage and manager pointing to same DB
    storage_2 = EnterpriseStorage(db_path=str(db_file))
    org_mgr_2 = EnterpriseOrganizationManager(storage=storage_2)
    restored_org = org_mgr_2.get_organization(org.org_id)
    assert restored_org is not None
    assert restored_org.name == "Durable Corp"
