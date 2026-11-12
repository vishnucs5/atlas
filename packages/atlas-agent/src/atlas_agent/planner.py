"""Structured planning engine, plan representation, and dynamic replanning."""

import time
from enum import StrEnum
from typing import Any

from atlas_core.contracts.action import ActionTarget, ComputerAction, ExpectedState
from atlas_core.contracts.observation import Observation
from pydantic import BaseModel, ConfigDict, Field


class StepStatus(StrEnum):
    """Execution status of an individual plan step."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PlanStatus(StrEnum):
    """Aggregate lifecycle status of an ExecutionPlan."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REPLANNING = "REPLANNING"


class ReplanBudgetExceededError(Exception):
    """Raised when an agent exceeds the maximum allowed replan iterations."""


class PlanBudget(BaseModel):
    """Hard constraints and ceilings bounding an execution plan."""

    model_config = ConfigDict(validate_assignment=True)

    max_steps: int = 30
    max_tokens: int = 200000
    max_cost_usd: float = 2.0
    timeout_seconds: int = 300
    max_replans: int = 3
    schema_version: str = "1.0"


class PlanStep(BaseModel):
    """Atomic step in a structured execution plan."""

    model_config = ConfigDict(validate_assignment=True)

    step_id: str
    description: str
    action_name: str
    target: ActionTarget | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    expected_state: ExpectedState | None = None
    rollback_action: ComputerAction | None = None
    status: StepStatus = StepStatus.PENDING
    schema_version: str = "1.0"


class ExecutionPlan(BaseModel):
    """Declarative, validated plan governing task execution."""

    model_config = ConfigDict(validate_assignment=True)

    plan_id: str
    task_id: str
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    budget: PlanBudget = Field(default_factory=PlanBudget)
    status: PlanStatus = PlanStatus.PENDING
    replan_count: int = 0
    schema_version: str = "1.0"


class StructuredPlanner:
    """Generates, validates, and refines structured execution plans."""

    def create_plan(
        self,
        task_id: str,
        goal: str,
        observation: Observation | None = None,
        budget: PlanBudget | None = None,
    ) -> ExecutionPlan:
        """Create an initial execution plan from a task objective."""
        return ExecutionPlan(
            plan_id=f"plan_{int(time.time())}",
            task_id=task_id,
            goal=goal,
            budget=budget or PlanBudget(),
        )

    def validate_plan(
        self,
        plan: ExecutionPlan,
        allowed_action_names: set[str] | None = None,
    ) -> list[str]:
        """Validate plan step syntax, dependencies, and permitted actions."""
        errors: list[str] = []
        step_ids = {s.step_id for s in plan.steps}

        for step in plan.steps:
            if allowed_action_names and step.action_name not in allowed_action_names:
                errors.append(
                    f"Step {step.step_id} specifies forbidden action '{step.action_name}'"
                )

            for dep in step.dependencies:
                if dep not in step_ids:
                    errors.append(f"Step {step.step_id} depends on unknown step '{dep}'")
                if dep == step.step_id:
                    errors.append(f"Step {step.step_id} cannot depend on itself")

        return errors

    def get_next_runnable_steps(self, plan: ExecutionPlan) -> list[PlanStep]:
        """Identify pending steps whose dependencies are all satisfied."""
        completed_step_ids = {s.step_id for s in plan.steps if s.status == StepStatus.COMPLETED}
        runnable = []
        for step in plan.steps:
            if step.status == StepStatus.PENDING:
                if all(dep in completed_step_ids for dep in step.dependencies):
                    runnable.append(step)
        return runnable

    def replan(
        self,
        current_plan: ExecutionPlan,
        failed_step_id: str,
        error_message: str,
        observation: Observation | None = None,
    ) -> ExecutionPlan:
        """Generate a recovery plan when a step fails, bounded by budget."""
        if current_plan.replan_count >= current_plan.budget.max_replans:
            raise ReplanBudgetExceededError(
                f"Replan limit reached ({current_plan.replan_count}/{current_plan.budget.max_replans}). "
                f"Cannot recover from failure in step {failed_step_id}: {error_message}"
            )

        new_plan = current_plan.model_copy(deep=True)
        new_plan.replan_count += 1
        new_plan.status = PlanStatus.IN_PROGRESS

        # Find failed step
        failed_step = next((s for s in new_plan.steps if s.step_id == failed_step_id), None)
        if failed_step:
            failed_step.status = StepStatus.FAILED

            # Add recovery alternative step
            recovery_step_id = f"{failed_step_id}_rec_{new_plan.replan_count}"
            recovery_step = PlanStep(
                step_id=recovery_step_id,
                description=f"Alternative approach for: {failed_step.description}",
                action_name=failed_step.action_name,
                target=failed_step.target,
                parameters={**failed_step.parameters, "retry_mode": "fallback"},
                dependencies=[d for d in failed_step.dependencies if d != failed_step_id],
                expected_state=failed_step.expected_state,
                status=StepStatus.PENDING,
            )
            new_plan.steps.append(recovery_step)

        return new_plan
