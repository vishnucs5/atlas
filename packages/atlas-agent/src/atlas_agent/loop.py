"""AutonomousAgentLoop orchestrating the 11-step observe-plan-act-verify cycle."""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from atlas_core.contracts.action import ActionTarget, ComputerAction
from atlas_core.contracts.event import EventType, ExecutionEvent
from atlas_core.contracts.model import ModelMessage, ModelRequest, ModelResponse, ToolDefinition
from atlas_core.contracts.observation import Observation
from atlas_core.contracts.policy import PolicyDecisionType
from atlas_core.contracts.session import Session
from atlas_core.contracts.task import Task, TaskStatus
from atlas_core.lifecycle import TaskStateMachine

from atlas_agent.context import ContextManager, TaskMemory
from atlas_agent.planner import PlanBudget, StructuredPlanner
from atlas_agent.safety import SafetyEngine


class AutonomousAgentLoop:
    """Executes the strict 11-step autonomous computer-use execution cycle."""

    def __init__(
        self,
        model_router: Any,
        action_firewall: Any,
        driver: Any,
        verification_engine: Any,
        event_store: Any,
        task_state_machine: TaskStateMachine | None = None,
        planner: StructuredPlanner | None = None,
        context_manager: ContextManager | None = None,
        safety_engine: SafetyEngine | None = None,
        approval_manager: Any | None = None,
    ) -> None:
        self._router = model_router
        self._firewall = action_firewall
        self._driver = driver
        self._verification = verification_engine
        self._event_store = event_store
        self._sm = task_state_machine or TaskStateMachine()
        self._planner = planner or StructuredPlanner()
        self._context_mgr = context_manager or ContextManager()
        self._safety = safety_engine or SafetyEngine()
        self._approval_mgr = approval_manager
        self._memory = TaskMemory()

    def _normalize_action_type(self, tool_name: str) -> str:
        """Convert snake_case tool names to dotted action types (e.g. browser_click -> browser.click)."""
        if "_" in tool_name and "." not in tool_name:
            prefix, rest = tool_name.split("_", 1)
            return f"{prefix}.{rest}"
        return tool_name

    async def _transition_task(
        self,
        task: Task,
        target_status: TaskStatus,
        *,
        session_id: str | None = None,
        reason: str | None = None,
    ) -> ExecutionEvent:
        """Atomically transition task status with monotonically sequenced event."""
        seq = 1
        if hasattr(self._event_store, "get_latest_sequence"):
            val = self._event_store.get_latest_sequence(task.task_id)
            if asyncio.iscoroutine(val):
                val = await val
            seq = (val or 0) + 1
        else:
            seq = int(time.time() * 1000) % 1000000

        evt = self._sm.transition_task(
            task,
            target_status,
            session_id=session_id,
            sequence=seq,
            reason=reason,
        )
        await self._store_event(evt)
        return evt

    async def _store_event(self, event: ExecutionEvent) -> None:
        """Append event to event store supporting both async and sync stores."""
        res = self._event_store.append_event(event)
        if asyncio.iscoroutine(res):
            await res

    async def _emit_event(
        self,
        task_id: str,
        session_id: str | None,
        event_type: EventType,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        """Record an immutable execution event."""
        seq = 1
        if hasattr(self._event_store, "get_latest_sequence"):
            val = self._event_store.get_latest_sequence(task_id)
            if asyncio.iscoroutine(val):
                val = await val
            seq = (val or 0) + 1
        else:
            seq = int(time.time() * 1000) % 1000000

        event = ExecutionEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            session_id=session_id,
            sequence=seq,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            payload=payload,
            correlation_id=correlation_id,
        )
        await self._store_event(event)

    async def run(
        self,
        task: Task,
        session: Session,
        budget: PlanBudget | None = None,
    ) -> Task:
        """Run the 11-step execution cycle until task completion or boundary ceiling."""
        plan_budget = budget or PlanBudget()
        start_time = time.perf_counter()
        current_step = 0
        total_tokens = 0
        total_cost = 0.0

        if task.status in (TaskStatus.CREATED, TaskStatus.READY, TaskStatus.QUEUED):
            await self._transition_task(task, TaskStatus.RUNNING, session_id=session.session_id)

        # Standard tool declarations presented to the model
        declared_tools = [
            ToolDefinition(
                name="browser_navigate",
                description="Navigate to a specified URL",
                parameters={
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            ),
            ToolDefinition(
                name="browser_click",
                description="Click an element by selector, text, or coordinates",
                parameters={
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "text": {"type": "string"},
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                    },
                },
            ),
            ToolDefinition(
                name="browser_type",
                description="Type text into an input field",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "selector": {"type": "string"},
                    },
                    "required": ["text"],
                },
            ),
            ToolDefinition(
                name="browser_wait",
                description="Wait for element or delay",
                parameters={"type": "object", "properties": {"ms": {"type": "integer"}}},
            ),
        ]

        while task.status == TaskStatus.RUNNING:
            current_step += 1
            step_corr_id = f"step_{current_step}_{uuid.uuid4().hex[:8]}"
            elapsed = time.perf_counter() - start_time

            # Safety check: enforce budgets and ceilings
            self._safety.check_budget(
                current_step=current_step,
                max_steps=plan_budget.max_steps,
                total_tokens=total_tokens,
                max_tokens=plan_budget.max_tokens,
                total_cost=total_cost,
                max_cost=plan_budget.max_cost_usd,
                elapsed_seconds=elapsed,
                timeout_seconds=float(plan_budget.timeout_seconds),
            )

            # Check if there is an approved action resuming from WAITING_APPROVAL
            if "pending_approval_action" in task.metadata:
                pending_dict = task.metadata.pop("pending_approval_action")
                tc_id = pending_dict.pop("_tool_call_id", None)
                req_id = pending_dict.pop("_approval_request_id", None)
                action = ComputerAction.model_validate(pending_dict)
                if not tc_id:
                    tc_id = action.parameters.get("_tool_call_id", f"tc_{action.action_id}")
                tc_name = action.action_type.replace(".", "_")

                # Enforce exact-bound cryptographic parameter verification and prevent replay
                if self._approval_mgr and req_id:
                    try:
                        self._approval_mgr.validate_action(req_id, action)
                        self._approval_mgr.mark_consumed(req_id)
                    except Exception as sec_err:
                        await self._emit_event(
                            task.task_id,
                            session.session_id,
                            EventType.ACTION_FAILED,
                            {
                                "action_id": action.action_id,
                                "error": f"Approval Security Violation: {sec_err}",
                            },
                            step_corr_id,
                        )
                        await self._transition_task(
                            task,
                            TaskStatus.FAILED,
                            session_id=session.session_id,
                            reason=f"Approval security validation failed: {sec_err}",
                        )
                        return task

                await self._emit_event(
                    task.task_id,
                    session.session_id,
                    EventType.ACTION_STARTED,
                    {"action_id": action.action_id, "approved": True},
                    step_corr_id,
                )
                result = await self._driver.execute(action)

                verified = True
                if action.expected_state:
                    page = getattr(self._driver, "active_page", None)
                    download_dir = getattr(self._driver, "downloads_path", None)
                    v_res = await self._verification.verify(
                        action.expected_state, page=page, download_dir=download_dir
                    )
                    verified = getattr(v_res, "verified", bool(v_res))
                    await self._emit_event(
                        task.task_id,
                        session.session_id,
                        EventType.VERIFICATION_COMPLETED,
                        {"verified": verified, "evidence": getattr(v_res, "evidence", {})},
                        step_corr_id,
                    )

                is_successful = (
                    getattr(result, "success", False)
                    or getattr(result, "status", "") == "completed"
                )
                if is_successful and verified:
                    await self._emit_event(
                        task.task_id,
                        session.session_id,
                        EventType.ACTION_COMPLETED,
                        {"action_id": action.action_id, "output": result.output},
                        step_corr_id,
                    )
                    tool_result_content = result.output or "Action executed successfully"
                else:
                    await self._emit_event(
                        task.task_id,
                        session.session_id,
                        EventType.ACTION_FAILED,
                        {
                            "action_id": action.action_id,
                            "error": result.error or "Verification failed",
                        },
                        step_corr_id,
                    )
                    tool_result_content = f"Action failed: {result.error or 'Verification failed'}"

                self._context_mgr.add_message(
                    ModelMessage(
                        role="tool",
                        tool_call_id=tc_id,
                        name=tc_name,
                        content=str(tool_result_content),
                    )
                )
                continue

            # Step 1: OBSERVE
            try:
                observation: Observation = await self._driver.observe()
            except TypeError:
                observation = await self._driver.observe(session.session_id)
            await self._emit_event(
                task.task_id,
                session.session_id,
                EventType.OBSERVATION_CAPTURED,
                {"observation_id": observation.observation_id},
                step_corr_id,
            )

            # Step 2: BUILD CONTEXT
            messages = self._context_mgr.build_prompt_context(
                task=task,
                current_observation=observation,
                memory=self._memory,
            )

            # Step 3: ASK MODEL
            req = ModelRequest(
                request_id=f"req_{step_corr_id}",
                task_id=task.task_id,
                model_name="default",
                system_prompt="You are ATLAS, an autonomous computer-use harness. Propose tool calls to accomplish the task.",
                messages=messages,
                tools=declared_tools,
            )
            await self._emit_event(
                task.task_id,
                session.session_id,
                EventType.MODEL_REQUESTED,
                {"request_id": req.request_id},
                step_corr_id,
            )

            resp: ModelResponse = await self._router.complete(req)
            if resp.usage:
                tokens = (
                    getattr(resp.usage, "total_tokens", 0)
                    if hasattr(resp.usage, "total_tokens")
                    else resp.usage.get("total_tokens", 0)
                )
                cost = (
                    getattr(resp.usage, "estimated_cost_usd", 0.0)
                    if hasattr(resp.usage, "estimated_cost_usd")
                    else resp.usage.get("estimated_cost_usd", 0.0)
                )
                total_tokens += tokens
                total_cost += cost

            await self._emit_event(
                task.task_id,
                session.session_id,
                EventType.MODEL_RESPONDED,
                {"response_id": resp.response_id, "tool_calls_count": len(resp.tool_calls)},
                step_corr_id,
            )

            # Step 4: VALIDATE RESPONSE
            if not resp.tool_calls:
                # Model provided final text response without tool calls -> Goal Accomplished!
                self._context_mgr.add_message(
                    ModelMessage(role="assistant", content=resp.content or "Completed")
                )
                # Constitutional Invariant: Must transition through VERIFYING before COMPLETED
                await self._transition_task(
                    task, TaskStatus.VERIFYING, session_id=session.session_id
                )
                await self._transition_task(
                    task, TaskStatus.COMPLETED, session_id=session.session_id
                )
                break

            # Handle first tool call in turn
            tool_call = resp.tool_calls[0]
            tc_name = (
                getattr(tool_call, "name", "")
                if hasattr(tool_call, "name")
                else tool_call.get("name", "")
            )
            tc_args = (
                getattr(tool_call, "arguments", {})
                if hasattr(tool_call, "arguments")
                else tool_call.get("arguments", {})
            )
            tc_id = (
                getattr(tool_call, "id", "")
                if hasattr(tool_call, "id")
                else tool_call.get("id", "")
            )

            # Step 5: PROPOSE ACTION
            action_type = self._normalize_action_type(tc_name)
            target = ActionTarget(strategy="parameters", parameters=tc_args) if tc_args else None
            idempotency_key = self._safety.compute_action_hash(action_type, target, tc_args)

            action = ComputerAction(
                action_id=f"act_{uuid.uuid4().hex[:12]}",
                task_id=task.task_id,
                session_id=session.session_id,
                action_type=action_type,
                target=target,
                parameters=tc_args,
                idempotency_key=idempotency_key,
            )

            # Check idempotency loop detector
            self._safety.check_and_record_action(
                action.action_type, action.target, action.parameters
            )

            await self._emit_event(
                task.task_id,
                session.session_id,
                EventType.ACTION_PROPOSED,
                {"action_id": action.action_id, "action_type": action.action_type},
                step_corr_id,
            )

            # Step 6: CHECK POLICY (Action Firewall)
            decision = self._firewall.evaluate(action)
            if asyncio.iscoroutine(decision):
                decision = await decision
            await self._emit_event(
                task.task_id,
                session.session_id,
                EventType.POLICY_EVALUATED,
                {"decision": decision.decision, "reason": decision.reason},
                step_corr_id,
            )

            if decision.decision == PolicyDecisionType.DENY:
                # DENIED by Action Firewall! Do NOT dispatch to driver!
                await self._emit_event(
                    task.task_id,
                    session.session_id,
                    EventType.ACTION_FAILED,
                    {"action_id": action.action_id, "error": f"Policy DENY: {decision.reason}"},
                    step_corr_id,
                )
                # Feed denial feedback to context manager
                self._context_mgr.add_message(
                    ModelMessage(
                        role="tool",
                        tool_call_id=tc_id,
                        name=tc_name,
                        content=f"Error: Action '{action.action_type}' was DENIED by the ATLAS Action Firewall: {decision.reason}",
                    )
                )
                continue

            # Step 7: REQUEST APPROVAL (if required)
            if decision.decision == PolicyDecisionType.REQUIRE_APPROVAL:
                req_id = None
                if self._approval_mgr:
                    risk_str = (
                        decision.risk_level.value
                        if hasattr(decision.risk_level, "value")
                        else str(decision.risk_level)
                    )
                    req = self._approval_mgr.create_request(
                        task_id=task.task_id,
                        action_id=action.action_id,
                        action_type=action.action_type,
                        parameters=action.parameters,
                        reason=decision.reason,
                        risk_level=risk_str,
                    )
                    req_id = req.request_id

                # Store pending action data in metadata so it can be resumed
                action_data = action.model_dump()
                action_data["_tool_call_id"] = tc_id
                if req_id:
                    action_data["_approval_request_id"] = req_id
                task.metadata["pending_approval_action"] = action_data

                payload: dict[str, Any] = {
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                }
                if req_id:
                    payload["request_id"] = req_id

                await self._emit_event(
                    task.task_id,
                    session.session_id,
                    EventType.APPROVAL_REQUESTED,
                    payload,
                    step_corr_id,
                )
                await self._transition_task(
                    task, TaskStatus.WAITING_APPROVAL, session_id=session.session_id
                )
                return task

            # Step 8: EXECUTE THROUGH ATLAS DRIVER
            await self._emit_event(
                task.task_id,
                session.session_id,
                EventType.ACTION_STARTED,
                {"action_id": action.action_id},
                step_corr_id,
            )
            result = await self._driver.execute(action)

            # Step 9: VERIFY (Deterministic Verification)
            verified = True
            if action.expected_state:
                page = getattr(self._driver, "active_page", None)
                download_dir = getattr(self._driver, "downloads_path", None)
                v_res = await self._verification.verify(
                    action.expected_state, page=page, download_dir=download_dir
                )
                verified = getattr(v_res, "verified", bool(v_res))
                await self._emit_event(
                    task.task_id,
                    session.session_id,
                    EventType.VERIFICATION_COMPLETED,
                    {"verified": verified, "evidence": getattr(v_res, "evidence", {})},
                    step_corr_id,
                )

            # Step 10: RECORD EVENTS
            is_successful = (
                getattr(result, "success", False) or getattr(result, "status", "") == "completed"
            )
            if is_successful and verified:
                await self._emit_event(
                    task.task_id,
                    session.session_id,
                    EventType.ACTION_COMPLETED,
                    {"action_id": action.action_id, "output": result.output},
                    step_corr_id,
                )
                tool_result_content = result.output or "Action executed successfully"
            else:
                await self._emit_event(
                    task.task_id,
                    session.session_id,
                    EventType.ACTION_FAILED,
                    {"action_id": action.action_id, "error": result.error or "Verification failed"},
                    step_corr_id,
                )
                tool_result_content = f"Action failed: {result.error or 'Verification failed'}"

            # Step 11: REPLAN / CONTINUE
            self._context_mgr.add_message(
                ModelMessage(
                    role="tool",
                    tool_call_id=tc_id,
                    name=tc_name,
                    content=str(tool_result_content),
                )
            )

        return task
