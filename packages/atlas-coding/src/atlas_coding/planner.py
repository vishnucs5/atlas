"""Software engineering planning and risk classification adapter."""

import re
from typing import Any

from atlas_core.contracts.coding import CodingTask
from atlas_core.contracts.policy import RiskLevel

from atlas_coding.explorer import RepositoryExplorer


class CodingPlanner:
    """Generates structured execution plans and risk profiles for coding tasks."""

    def __init__(self, explorer: RepositoryExplorer) -> None:
        self.explorer = explorer

    def find_candidate_files(self, objective: str) -> list[str]:
        """Heuristically identify files relevant to the given engineering objective."""
        candidates: list[str] = []
        words = re.findall(r"\b[a-zA-Z0-9_\-\.]+\b", objective.lower())

        for meta in self.explorer.discover_files(max_count=200):
            rel_lower = meta.rel_path.lower()
            for word in words:
                if len(word) > 2 and word in rel_lower:
                    candidates.append(meta.rel_path)
                    break
        return candidates[:10]

    def create_plan(self, task: CodingTask) -> dict[str, Any]:
        """Construct a structured, multi-phase engineering plan."""
        relevant_files = self.find_candidate_files(task.objective)
        manifests = self.explorer.discover_project_manifests()

        steps = [
            {
                "step_id": 1,
                "name": "Repository & Context Analysis",
                "description": f"Inspect repository structure, manifests ({list(manifests.values())}), and target files.",
                "risk_level": RiskLevel.LOW.value,
                "requires_approval": False,
                "target_files": relevant_files,
            },
            {
                "step_id": 2,
                "name": "Authorized Implementation & File Modification",
                "description": f"Apply required code changes to achieve objective: '{task.objective}'.",
                "risk_level": RiskLevel.HIGH.value,
                "requires_approval": True,
                "target_files": relevant_files,
            },
            {
                "step_id": 3,
                "name": "Test & Regression Verification",
                "description": "Execute automated test suites to verify functionality and prevent regressions.",
                "risk_level": RiskLevel.HIGH.value,
                "requires_approval": False,
                "framework": "detected",
            },
            {
                "step_id": 4,
                "name": "Diff Review & Post-Condition Audit",
                "description": "Deterministic verification of modified files against expected cryptographic hashes and clean working tree.",
                "risk_level": RiskLevel.LOW.value,
                "requires_approval": False,
            },
        ]

        return {
            "objective": task.objective,
            "relevant_files": relevant_files,
            "manifests": manifests,
            "steps": steps,
            "estimated_risk": RiskLevel.HIGH.value,
        }
