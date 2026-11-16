"""ATLAS Perception-Driven Planning & Action Firewall Integration.

Bridges visual perception models to the hierarchical planner, computes grounded
coordinates, handles visual uncertainty, and enforces Action Firewall policy gating.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from atlas_multimodal.grounding import (
    ScreenGeometry,
    StaleCoordinateGuard,
    VisualGroundingTransformer,
)
from atlas_multimodal.visual import (
    VisualObservation,
    VisualPerceptionEngine,
)


class PerceptionPlannerError(Exception):
    """Base exception for perception-driven planning."""


class PerceptionUncertaintyError(PerceptionPlannerError):
    """Raised when element detection confidence falls below the autonomous execution threshold."""


class PerceptionActionBlockedError(PerceptionPlannerError):
    """Raised when the Action Firewall denies execution of a perception-proposed action."""


class PlannedVisualAction(BaseModel):
    """A fully grounded action derived from visual perception, ready for authorization."""

    action_id: str = Field(default_factory=lambda: f"act_{uuid.uuid4().hex[:8]}")
    action_type: str
    target_element_id: str | None = None
    target_label: str | None = None
    grounded_coordinates: tuple[int, int] | None = None
    input_text: str | None = None
    confidence: float = 1.0
    requires_human_approval: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


import uuid  # noqa: E402


class PerceptionPlannerBridge:
    """Coordinates between perception, grounding, planning, and policy authorization."""

    def __init__(
        self,
        action_firewall: Any | None = None,
        stale_guard: StaleCoordinateGuard | None = None,
        uncertainty_threshold: float = 0.85,
    ) -> None:
        self.action_firewall = action_firewall
        self.stale_guard = stale_guard or StaleCoordinateGuard(max_age_seconds=5.0)
        self.transformer = VisualGroundingTransformer()
        self.uncertainty_threshold = uncertainty_threshold

    def plan_action_for_element(
        self,
        observation: VisualObservation,
        target_label: str,
        geometry: ScreenGeometry,
        action_type: str = "click",
        input_text: str | None = None,
        current_time: float | None = None,
    ) -> PlannedVisualAction:
        """Ground a visual action to physical coordinates, checking freshness and confidence."""
        # 1. Enforce freshness invariant
        self.stale_guard.validate(observation, current_time=current_time)

        # 2. Locate target element
        elem = observation.find_element_by_label(target_label)
        if elem is None:
            raise PerceptionUncertaintyError(
                f"Element '{target_label}' could not be identified in visual observation "
                f"'{observation.observation_id}'."
            )

        # 3. Enforce boundary invariant on target
        self.stale_guard.validate_bounds(elem.bounding_box)

        # 4. Transform normalized coordinates to physical screen coordinates
        coords = self.transformer.normalized_to_screen(
            box=elem.bounding_box,
            geometry=geometry,
            viewport_w=observation.viewport_width,
            viewport_h=observation.viewport_height,
        )

        # 5. Check confidence threshold
        needs_approval = elem.confidence < self.uncertainty_threshold

        return PlannedVisualAction(
            action_type=action_type,
            target_element_id=elem.element_id,
            target_label=elem.label,
            grounded_coordinates=coords,
            input_text=input_text,
            confidence=elem.confidence,
            requires_human_approval=needs_approval,
            metadata={"observation_id": observation.observation_id},
        )

    def authorize_action(
        self,
        action: PlannedVisualAction,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Evaluate action against the Action Firewall, returning 'ALLOW' or 'REQUIRE_APPROVAL'."""
        ctx = context or {}

        # If already flagged for low confidence, require approval
        if action.requires_human_approval:
            return "REQUIRE_APPROVAL"

        # If Action Firewall is configured, consult it
        if self.action_firewall is not None:
            action_type_str = f"ui_{action.action_type}"
            if "delete" in (action.target_label or "").lower():
                action_type_str += "_danger"

            from atlas_core.contracts.action import ComputerAction

            comp_action = ComputerAction(
                action_id=action.action_id,
                task_id=str(ctx.get("task_id", "task_perception")),
                session_id=str(ctx.get("session_id", "session_perception")),
                action_type=action_type_str,
                idempotency_key=f"idem_{action.action_id}",
                parameters={
                    "coordinates": action.grounded_coordinates,
                    "target_label": action.target_label,
                    "input_text": action.input_text,
                    **ctx,
                },
            )
            decision = self.action_firewall.evaluate(comp_action)

            decision_str = str(getattr(decision, "decision", decision)).upper()
            if "DENY" in decision_str:
                raise PerceptionActionBlockedError(
                    f"Action Firewall blocked action '{action.action_type}' on '{action.target_label}'."
                )
            if "APPROVAL" in decision_str:
                action.requires_human_approval = True
                return "REQUIRE_APPROVAL"
            return "ALLOW"

        return "ALLOW"

    @classmethod
    def verify_post_action_transition(
        cls,
        pre_obs: VisualObservation,
        post_obs: VisualObservation,
        expect_transition: bool = True,
    ) -> bool:
        """Verify that a visual action resulted in an expected screen transition."""
        diff = VisualPerceptionEngine.compare_visual_states(pre_obs, post_obs)
        if expect_transition:
            # Must not be identical if a transition was expected
            return not diff["identical"]
        return True
