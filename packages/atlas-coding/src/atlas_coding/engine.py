"""ATLAS Autonomous Coding Engine - orchestrating the full engineering lifecycle."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_core.contracts.coding import (
    CodingTask,
    FileChange,
    TestResultSummary,
)
from atlas_core.contracts.task import TaskPriority, TaskStatus
from atlas_policy.firewall import ActionFirewall

from atlas_coding.explorer import RepositoryExplorer
from atlas_coding.file_ops import AuthorizedFileOperations
from atlas_coding.git import GitPorcelain
from atlas_coding.patch import PatchEngine
from atlas_coding.planner import CodingPlanner
from atlas_coding.terminal import AuthorizedTerminalDriver
from atlas_coding.test_runner import TestRunner


class CodingEngine:
    """Integrated engine coordinating autonomous repository exploration, planning,

    firewall-evaluated modification, testing, and deterministic verification.
    """

    def __init__(
        self,
        repo_root: str | Path,
        firewall: ActionFirewall | None = None,
        auto_approve: bool = True,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.firewall = firewall or ActionFirewall()
        self.auto_approve = auto_approve

        self.explorer = RepositoryExplorer(repo_root=self.repo_root)
        self.file_ops = AuthorizedFileOperations(
            explorer=self.explorer,
            firewall=self.firewall,
            auto_approve_safe_actions=self.auto_approve,
        )
        self.patch_engine = PatchEngine(file_ops=self.file_ops)
        self.terminal = AuthorizedTerminalDriver(
            explorer=self.explorer,
            firewall=self.firewall,
            auto_approve_safe_commands=self.auto_approve,
        )
        self.git = GitPorcelain(explorer=self.explorer, terminal=self.terminal)
        self.planner = CodingPlanner(explorer=self.explorer)
        self.test_runner = TestRunner(explorer=self.explorer, terminal=self.terminal)

    def create_task(
        self,
        user_request: str,
        workspace_id: str = "default",
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> CodingTask:
        """Initialize a new CodingTask contract."""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        return CodingTask(
            task_id=task_id,
            workspace_id=workspace_id,
            user_request=user_request,
            repo_root=str(self.repo_root),
            objective=user_request,
            status=TaskStatus.CREATED,
            priority=priority,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    def plan_task(self, task: CodingTask) -> CodingTask:
        """Generate structured plan and risk assessment for the task."""
        task.status = TaskStatus.PLANNING
        plan_data = self.planner.create_plan(task)
        task.plan = plan_data
        task.relevant_files = plan_data.get("relevant_files", [])
        task.action_history.append(
            {
                "action": "plan_generated",
                "timestamp": datetime.now(UTC).isoformat(),
                "steps_count": len(plan_data.get("steps", [])),
            }
        )
        task.updated_at = datetime.now(UTC)
        return task

    def apply_file_modification(
        self,
        task: CodingTask,
        rel_path: str,
        content: str,
        is_new: bool = False,
    ) -> FileChange:
        """Apply a direct file creation or modification through the Action Firewall."""
        task.status = TaskStatus.RUNNING
        if is_new:
            fc = self.file_ops.create_file(rel_path, content)
        else:
            fc = self.file_ops.write_file(rel_path, content)

        task.file_changes.append(fc)
        task.action_history.append(
            {
                "action": "file_modified",
                "path": rel_path,
                "change_type": fc.change_type.value,
                "after_hash": fc.after_hash,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        task.updated_at = datetime.now(UTC)
        return fc

    def apply_diff(self, task: CodingTask, diff_text: str) -> list[FileChange]:
        """Apply a unified diff transactionally to the repository."""
        changes = self.patch_engine.apply_patch(diff_text)
        task.file_changes.extend(changes)
        task.action_history.append(
            {
                "action": "patch_applied",
                "files_count": len(changes),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        task.updated_at = datetime.now(UTC)
        return changes

    def run_tests(
        self,
        task: CodingTask,
        custom_command: list[str] | None = None,
    ) -> TestResultSummary:
        """Run project tests and record outcomes in task."""
        summary = self.test_runner.run_tests(custom_command=custom_command)
        task.test_results.append(summary)
        task.action_history.append(
            {
                "action": "tests_executed",
                "framework": summary.framework,
                "exit_code": summary.exit_code,
                "passed": summary.passed_count,
                "failed": summary.failed_count,
                "is_success": summary.is_success,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        task.updated_at = datetime.now(UTC)
        return summary

    def verify_task(self, task: CodingTask) -> dict[str, Any]:
        """Deterministically verify all modified files and test assertions.

        In accordance with the Verification Invariant:
        An action is never reported as successful without deterministic post-condition verification.
        """
        verification_passed = True
        file_checks: list[dict[str, Any]] = []

        # 1. Verify filesystem post-conditions
        for change in task.file_changes:
            safe_p = self.explorer.resolve_safe_path(change.path)
            if change.change_type.value == "DELETE":
                exists = safe_p.exists()
                check_ok = not exists
            else:
                exists = safe_p.is_file()
                actual_hash = self.file_ops._compute_sha256(safe_p) if exists else None
                check_ok = exists and (actual_hash == change.after_hash)

            if not check_ok:
                verification_passed = False

            file_checks.append(
                {
                    "path": change.path,
                    "change_type": change.change_type.value,
                    "verified": check_ok,
                }
            )

        # 2. Verify test outcomes if tests were executed
        test_passed = True
        if task.test_results:
            latest_test = task.test_results[-1]
            test_passed = latest_test.is_success
            if not test_passed:
                verification_passed = False

        evidence = {
            "verified_at": datetime.now(UTC).isoformat(),
            "all_passed": verification_passed,
            "file_checks": file_checks,
            "test_checks_passed": test_passed,
        }

        task.verification_evidence = evidence
        task.status = TaskStatus.COMPLETED if verification_passed else TaskStatus.FAILED
        task.updated_at = datetime.now(UTC)
        return evidence

    def execute_lifecycle(
        self,
        user_request: str,
        files_to_create: dict[str, str] | None = None,
        files_to_modify: dict[str, str] | None = None,
        unified_diff: str | None = None,
        run_tests: bool = True,
    ) -> CodingTask:
        """Run the full autonomous coding lifecycle:

        OBSERVE -> PLAN -> FIREWALL -> APPROVAL -> EXECUTE -> VERIFY -> COMPLETE
        """
        task = self.create_task(user_request=user_request)

        # 1. Plan
        self.plan_task(task)

        # 2. Execute File Creations
        if files_to_create:
            for p, content in files_to_create.items():
                self.apply_file_modification(task, rel_path=p, content=content, is_new=True)

        # 3. Execute File Modifications
        if files_to_modify:
            for p, content in files_to_modify.items():
                self.apply_file_modification(task, rel_path=p, content=content, is_new=False)

        # 4. Apply Unified Diffs
        if unified_diff:
            self.apply_diff(task, unified_diff)

        # 5. Run Tests
        if run_tests:
            self.run_tests(task)

        # 6. Verify Deterministic Post-Conditions
        self.verify_task(task)

        return task
