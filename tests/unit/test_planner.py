"""Unit tests for StructuredPlanner, ExecutionPlan, PlanStep, and dynamic replanning."""

import pytest
from atlas_agent.planner import (
    ExecutionPlan,
    PlanBudget,
    PlanStatus,
    PlanStep,
    ReplanBudgetExceededError,
    StepStatus,
    StructuredPlanner,
)
from atlas_core.contracts.action import ActionTarget, ExpectedState
from atlas_core.contracts.observation import Observation


def test_plan_step_and_execution_plan_creation():
    """Verify ExecutionPlan and PlanStep contract validation and serialization."""
    step1 = PlanStep(
        step_id="step-1",
        description="Navigate to website",
        action_name="browser.navigate",
        parameters={"url": "https://example.com"},
        expected_state=ExpectedState(condition="url_matches", target="https://example.com"),
    )
    step2 = PlanStep(
        step_id="step-2",
        description="Click download link",
        action_name="browser.click",
        target=ActionTarget(strategy="css", value="#download-btn"),
        dependencies=["step-1"],
    )

    plan = ExecutionPlan(
        plan_id="plan-100",
        task_id="task-200",
        goal="Download report",
        steps=[step1, step2],
        budget=PlanBudget(max_steps=10, max_replans=2),
    )

    assert plan.plan_id == "plan-100"
    assert len(plan.steps) == 2
    assert plan.status == PlanStatus.PENDING
    assert plan.budget.max_replans == 2

    # Roundtrip JSON
    dumped = plan.model_dump_json()
    reloaded = ExecutionPlan.model_validate_json(dumped)
    assert reloaded.steps[0].action_name == "browser.navigate"
    assert reloaded.steps[1].dependencies == ["step-1"]


def test_get_next_runnable_steps():
    """Verify dependency graph resolution for runnable plan steps."""
    planner = StructuredPlanner()
    step1 = PlanStep(step_id="s1", description="Step 1", action_name="browser.navigate")
    step2 = PlanStep(
        step_id="s2", description="Step 2", action_name="browser.click", dependencies=["s1"]
    )
    step3 = PlanStep(
        step_id="s3", description="Step 3", action_name="browser.type", dependencies=["s1"]
    )
    step4 = PlanStep(
        step_id="s4", description="Step 4", action_name="browser.click", dependencies=["s2", "s3"]
    )

    plan = ExecutionPlan(
        plan_id="p1", task_id="t1", goal="Goal", steps=[step1, step2, step3, step4]
    )

    # Initially, only s1 is runnable
    runnable = planner.get_next_runnable_steps(plan)
    assert [s.step_id for s in runnable] == ["s1"]

    # Mark s1 complete -> s2 and s3 become runnable
    step1.status = StepStatus.COMPLETED
    runnable = planner.get_next_runnable_steps(plan)
    assert sorted([s.step_id for s in runnable]) == ["s2", "s3"]

    # Mark s2 complete -> s4 is still waiting on s3
    step2.status = StepStatus.COMPLETED
    runnable = planner.get_next_runnable_steps(plan)
    assert [s.step_id for s in runnable] == ["s3"]

    # Mark s3 complete -> s4 becomes runnable
    step3.status = StepStatus.COMPLETED
    runnable = planner.get_next_runnable_steps(plan)
    assert [s.step_id for s in runnable] == ["s4"]


def test_plan_step_validation():
    """Verify validation of plan steps against permitted action schemas."""
    planner = StructuredPlanner()
    step_valid = PlanStep(step_id="s1", description="Navigate", action_name="browser.navigate")
    step_invalid = PlanStep(
        step_id="s2", description="Dangerous format", action_name="os.format_disk"
    )

    plan = ExecutionPlan(plan_id="p1", task_id="t1", goal="Goal", steps=[step_valid, step_invalid])

    allowed_actions = {"browser.navigate", "browser.click", "browser.type", "browser.fill"}
    errors = planner.validate_plan(plan, allowed_action_names=allowed_actions)
    assert len(errors) == 1
    assert "os.format_disk" in errors[0]


def test_dynamic_replanning_and_budget_bounds():
    """Verify dynamic replanning on step failure and hard replan limit enforcement."""
    planner = StructuredPlanner()
    step1 = PlanStep(
        step_id="s1",
        description="Navigate",
        action_name="browser.navigate",
        status=StepStatus.COMPLETED,
    )
    step2 = PlanStep(
        step_id="s2",
        description="Click selector",
        action_name="browser.click",
        status=StepStatus.FAILED,
    )

    plan = ExecutionPlan(
        plan_id="p1",
        task_id="t1",
        goal="Download CSV",
        steps=[step1, step2],
        budget=PlanBudget(max_replans=2),
    )

    from datetime import UTC, datetime

    obs = Observation(
        observation_id="obs_1",
        task_id="t1",
        session_id="sess_1",
        url="https://example.com",
        timestamp=datetime.now(UTC),
    )

    # Replan 1
    new_plan = planner.replan(
        plan,
        failed_step_id="s2",
        error_message="Element not found with css #download",
        observation=obs,
    )
    assert new_plan.replan_count == 1
    assert new_plan.status == PlanStatus.IN_PROGRESS
    assert len(new_plan.steps) >= 2

    # Replan 2
    new_plan.steps[-1].status = StepStatus.FAILED
    new_plan_2 = planner.replan(
        new_plan,
        failed_step_id=new_plan.steps[-1].step_id,
        error_message="Timeout",
        observation=obs,
    )
    assert new_plan_2.replan_count == 2

    # Replan 3 -> Exceeds max_replans=2 -> raises ReplanBudgetExceededError
    new_plan_2.steps[-1].status = StepStatus.FAILED
    with pytest.raises(ReplanBudgetExceededError):
        planner.replan(
            new_plan_2,
            failed_step_id=new_plan_2.steps[-1].step_id,
            error_message="Another failure",
            observation=obs,
        )
