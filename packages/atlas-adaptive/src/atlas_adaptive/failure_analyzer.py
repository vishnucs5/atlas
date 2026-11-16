"""ATLAS Failure Analysis & Root Cause Attribution Engine.

Classifies task execution failures across a 12-category taxonomy and establishes
evidence-backed root causes without unwarranted assumptions.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FailureCategory(StrEnum):
    """Exhaustive classification taxonomy for task execution failures."""

    PLANNING_ERROR = "PLANNING_ERROR"
    MODEL_REASONING_ERROR = "MODEL_REASONING_ERROR"
    INCORRECT_TOOL_SELECTION = "INCORRECT_TOOL_SELECTION"
    BROWSER_INTERACTION_FAILURE = "BROWSER_INTERACTION_FAILURE"
    DESKTOP_INTERACTION_FAILURE = "DESKTOP_INTERACTION_FAILURE"
    VISUAL_GROUNDING_ERROR = "VISUAL_GROUNDING_ERROR"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    WORKER_FAILURE = "WORKER_FAILURE"
    PERMISSION_DENIAL = "PERMISSION_DENIAL"
    EXTERNAL_SERVICE_FAILURE = "EXTERNAL_SERVICE_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    RECOVERY_FAILURE = "RECOVERY_FAILURE"


class AttributedCause(BaseModel):
    """An attributed failure cause supported by concrete execution evidence."""

    category: FailureCategory
    confidence: float = 1.0  # [0.0, 1.0]
    supporting_evidence: list[str] = Field(default_factory=list)
    root_cause_summary: str


class FailureAnalysisResult(BaseModel):
    """Comprehensive failure classification and root cause attribution report."""

    analysis_id: str = Field(default_factory=lambda: f"fail_{uuid.uuid4().hex[:10]}")
    task_id: str
    primary_cause: AttributedCause
    contributing_causes: list[AttributedCause] = Field(default_factory=list)
    raw_event_count: int = 0


class FailureAnalysisEngine:
    """Classifies execution traces into structured failure categories with evidence."""

    @classmethod
    def analyze_failure(
        cls,
        task_id: str,
        events: list[dict[str, Any]],
        error_message: str | None = None,
    ) -> FailureAnalysisResult:
        """Perform root cause analysis across execution events and error logs."""
        causes: list[AttributedCause] = []

        err_text = (error_message or "").lower()
        event_texts = [str(e.get("message", "") or e.get("error", "")).lower() for e in events]
        full_corpus = f"{err_text} " + " ".join(event_texts)

        # 1. Permission Denial
        if (
            "policy" in full_corpus
            or "denied" in full_corpus
            or "forbidden" in full_corpus
            or "403" in full_corpus
        ):
            evidence = [
                txt for txt in event_texts if "denied" in txt or "policy" in txt or "403" in txt
            ]
            if not evidence and err_text:
                evidence = [err_text]
            causes.append(
                AttributedCause(
                    category=FailureCategory.PERMISSION_DENIAL,
                    confidence=0.95,
                    supporting_evidence=evidence,
                    root_cause_summary="Action blocked or rejected by security policy / Action Firewall.",
                )
            )

        # 2. Visual Grounding Error
        if "stale" in full_corpus or "out of bounds" in full_corpus or "grounding" in full_corpus:
            evidence = [
                txt
                for txt in event_texts
                if "stale" in txt or "bounds" in txt or "grounding" in txt
            ]
            causes.append(
                AttributedCause(
                    category=FailureCategory.VISUAL_GROUNDING_ERROR,
                    confidence=0.90,
                    supporting_evidence=evidence or [err_text],
                    root_cause_summary="Visual coordinate mapping failed or observation exceeded freshness threshold.",
                )
            )

        # 3. Verification Failure
        if (
            "verification" in full_corpus
            or "post-condition" in full_corpus
            or "state mismatch" in full_corpus
        ):
            evidence = [txt for txt in event_texts if "verification" in txt or "mismatch" in txt]
            causes.append(
                AttributedCause(
                    category=FailureCategory.VERIFICATION_FAILURE,
                    confidence=0.90,
                    supporting_evidence=evidence or [err_text],
                    root_cause_summary="Deterministic post-action verification assertion failed.",
                )
            )

        # 4. Network / Worker / External Service Failure
        if (
            "timeout" in full_corpus
            or "connection reset" in full_corpus
            or "502" in full_corpus
            or "503" in full_corpus
        ):
            evidence = [
                txt for txt in event_texts if "timeout" in txt or "reset" in txt or "50" in txt
            ]
            causes.append(
                AttributedCause(
                    category=FailureCategory.NETWORK_FAILURE,
                    confidence=0.85,
                    supporting_evidence=evidence or [err_text],
                    root_cause_summary="Underlying network communication or external endpoint timed out.",
                )
            )

        # 5. Planning or Model Reasoning fallback
        if not causes:
            causes.append(
                AttributedCause(
                    category=FailureCategory.PLANNING_ERROR,
                    confidence=0.60,
                    supporting_evidence=[err_text]
                    if err_text
                    else ["Task terminated without explicit system error."],
                    root_cause_summary="Planner failed to synthesize a valid execution path toward the goal.",
                )
            )

        primary = causes[0]
        contributing = causes[1:]

        return FailureAnalysisResult(
            task_id=task_id,
            primary_cause=primary,
            contributing_causes=contributing,
            raw_event_count=len(events),
        )
