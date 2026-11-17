"""Agent conflict detection and auditable resolution engine."""

import threading
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from atlas_core.contracts.graph import DependencyType, TaskGraph, TaskNode
from pydantic import BaseModel, ConfigDict, Field


class ConflictType(StrEnum):
    """Categorization of agent execution conflicts."""

    OVERLAPPING_FILE_WRITE = "OVERLAPPING_FILE_WRITE"
    CONFLICTING_REQUIREMENTS = "CONFLICTING_REQUIREMENTS"
    INCOMPATIBLE_INTERFACES = "INCOMPATIBLE_INTERFACES"
    DUPLICATE_WORK = "DUPLICATE_WORK"
    RESOURCE_CONTENTION = "RESOURCE_CONTENTION"
    CONTRADICTORY_DECISIONS = "CONTRADICTORY_DECISIONS"


class DetectedConflict(BaseModel):
    """Formal record of a detected execution or architectural conflict."""

    model_config = ConfigDict(validate_assignment=True)

    conflict_id: str
    conflict_type: ConflictType
    involved_nodes: list[str] = Field(default_factory=list)
    involved_agents: list[str] = Field(default_factory=list)
    target_resource: str = ""
    description: str
    severity: str = "HIGH"
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConflictResolutionDecision(BaseModel):
    """Auditable resolution record documenting how a conflict was resolved."""

    model_config = ConfigDict(validate_assignment=True)

    resolution_id: str
    conflict_id: str
    resolved_by: str
    resolution_strategy: str
    reasoning: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConflictManager:
    """Detects concurrency, file write, and semantic conflicts across specialist tasks."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.detected_conflicts: list[DetectedConflict] = []
        self.resolution_history: list[ConflictResolutionDecision] = []

    def detect_file_conflicts(self, graph: TaskGraph) -> list[DetectedConflict]:
        """Detect if multiple task nodes target the same file for modification."""
        with self._lock:
            conflicts: list[DetectedConflict] = []
            file_to_nodes: dict[str, list[str]] = {}

            for nid, node in graph.nodes.items():
                target_file = (
                    node.parameters.get("file_path")
                    or node.parameters.get("target_file")
                    or node.parameters.get("filepath")
                )
                if target_file:
                    clean_file = target_file.replace("\\", "/").lstrip("/")
                    file_to_nodes.setdefault(clean_file, []).append(nid)

            for target_file, nids in file_to_nodes.items():
                if len(nids) > 1:
                    cid = f"conf_{uuid.uuid4().hex[:8]}"
                    c = DetectedConflict(
                        conflict_id=cid,
                        conflict_type=ConflictType.OVERLAPPING_FILE_WRITE,
                        involved_nodes=nids,
                        target_resource=target_file,
                        description=(
                            f"Multiple concurrent tasks {nids} attempt to modify file '{target_file}'. "
                            "Parallel execution would cause race condition / overwrite."
                        ),
                        severity="CRITICAL",
                    )
                    conflicts.append(c)
                    self.detected_conflicts.append(c)

            return conflicts

    def serialize_conflicting_nodes(self, graph: TaskGraph) -> int:
        """Enforce sequential dependency edges between nodes targeting identical files.

        Returns the number of injected serialization dependencies.
        """
        with self._lock:
            conflicts = self.detect_file_conflicts(graph)
            injected_count = 0

            for conflict in conflicts:
                if conflict.conflict_type == ConflictType.OVERLAPPING_FILE_WRITE:
                    nids = conflict.involved_nodes
                    # Chain nids sequentially: nids[0] -> nids[1] -> nids[2]...
                    for i in range(len(nids) - 1):
                        first_nid = nids[i]
                        second_nid = nids[i + 1]
                        second_node = graph.nodes[second_nid]

                        if first_nid not in second_node.dependencies:
                            second_node.dependencies.append(first_nid)
                            second_node.dependency_type = DependencyType.HARD
                            injected_count += 1

                    # Record resolution
                    self.record_resolution(
                        ConflictResolutionDecision(
                            resolution_id=f"res_{uuid.uuid4().hex[:8]}",
                            conflict_id=conflict.conflict_id,
                            resolved_by="supervisor.conflict_manager",
                            resolution_strategy="SERIALIZE_DEPENDENCY",
                            reasoning=(
                                f"Injected sequential dependency between tasks {nids} on file '{conflict.target_resource}' "
                                "to eliminate concurrent file write race conditions."
                            ),
                        )
                    )

            return injected_count

    def detect_semantic_conflicts(
        self,
        node_a: TaskNode,
        node_b: TaskNode,
    ) -> DetectedConflict | None:
        """Detect semantic incompatibilities between two tasks (e.g., conflicting flags)."""
        with self._lock:
            params_a = node_a.parameters
            params_b = node_b.parameters

            # Check for mutually exclusive architecture patterns
            if params_a.get("architecture") and params_b.get("architecture"):
                if params_a["architecture"] != params_b["architecture"]:
                    cid = f"conf_{uuid.uuid4().hex[:8]}"
                    c = DetectedConflict(
                        conflict_id=cid,
                        conflict_type=ConflictType.CONFLICTING_REQUIREMENTS,
                        involved_nodes=[node_a.node_id, node_b.node_id],
                        target_resource="architecture",
                        description=(
                            f"Contradictory architecture decisions: '{params_a['architecture']}' vs "
                            f"'{params_b['architecture']}'."
                        ),
                        severity="HIGH",
                    )
                    self.detected_conflicts.append(c)
                    return c

            return None

    def record_resolution(self, decision: ConflictResolutionDecision) -> None:
        """Record an auditable resolution decision."""
        with self._lock:
            self.resolution_history.append(decision)

    def get_audit_history(self) -> list[ConflictResolutionDecision]:
        """Return full auditable decision log."""
        with self._lock:
            return list(self.resolution_history)
