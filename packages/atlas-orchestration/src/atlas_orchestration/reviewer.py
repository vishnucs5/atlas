"""IndependentReviewer providing deterministic verification of task requirements, deliverables, and evidence."""

from enum import StrEnum
from typing import Any

from atlas_core.contracts.graph import NodeStatus, TaskGraph
from pydantic import BaseModel, ConfigDict, Field

from atlas_orchestration.memory import SharedMemoryEngine


class ReviewVerdict(StrEnum):
    """Outcome of independent QA quality assurance review."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewResult(BaseModel):
    """Formal audit assessment produced by the IndependentReviewer."""

    model_config = ConfigDict(validate_assignment=True)

    verdict: ReviewVerdict
    feedback: str
    missing_criteria: list[str] = Field(default_factory=list)
    verified_nodes: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class IndependentReviewer:
    """Independent verification agent ensuring tasks are not marked complete without verified evidence."""

    def __init__(self, memory: SharedMemoryEngine) -> None:
        self.memory = memory

    def evaluate_task_graph(
        self,
        graph: TaskGraph,
        required_outputs: list[str] | None = None,
        min_completed_nodes: int = 1,
    ) -> ReviewResult:
        """Deterministically audit the completed task DAG against completion criteria and evidence."""
        missing: list[str] = []
        verified: list[str] = []

        # 1. Verify minimum node threshold
        completed_nodes = [n for n in graph.nodes.values() if n.status == NodeStatus.COMPLETED]
        if len(completed_nodes) < min_completed_nodes:
            missing.append(
                f"Insufficient completed nodes: required at least {min_completed_nodes}, found {len(completed_nodes)}."
            )

        # 2. Verify all nodes in graph reached valid terminal state (no stuck RUNNING or PENDING nodes)
        for nid, node in graph.nodes.items():
            if not node.is_terminal():
                missing.append(f"Node '{nid}' is in non-terminal state '{node.status.value}'.")
            elif node.status == NodeStatus.COMPLETED:
                # Assert completed nodes produced valid non-empty output
                if node.output is None:
                    missing.append(f"Node '{nid}' completed without producing output artifacts.")
                else:
                    verified.append(nid)
            elif node.status == NodeStatus.FAILED:
                missing.append(f"Hard node '{nid}' failed: {node.error}")

        # 3. Verify specific required output keys
        if required_outputs:
            all_outputs: dict[str, Any] = {}
            for node in completed_nodes:
                if node.output:
                    all_outputs.update(node.output)

            for req_key in required_outputs:
                if req_key not in all_outputs:
                    missing.append(f"Required deliverable output '{req_key}' was not produced.")

        # Verdict determination
        if missing:
            return ReviewResult(
                verdict=ReviewVerdict.REJECTED,
                feedback=f"Independent review failed. Missing criteria: {'; '.join(missing)}",
                missing_criteria=missing,
                verified_nodes=verified,
                confidence=0.0,
            )

        return ReviewResult(
            verdict=ReviewVerdict.APPROVED,
            feedback="All deliverables, evidence, and state verifications successfully satisfied.",
            missing_criteria=[],
            verified_nodes=verified,
            confidence=1.0,
        )
