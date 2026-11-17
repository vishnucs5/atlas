"""Test discovery, execution, and structured outcome summarization."""

import re
from datetime import UTC, datetime

from atlas_core.contracts.coding import TestResultSummary

from atlas_coding.explorer import RepositoryExplorer
from atlas_coding.terminal import AuthorizedTerminalDriver

PYTEST_PASSED_RE = re.compile(r"(\d+)\s+passed")
PYTEST_FAILED_RE = re.compile(r"(\d+)\s+failed")
PYTEST_SKIPPED_RE = re.compile(r"(\d+)\s+skipped")

JEST_PASSED_RE = re.compile(r"(\d+)\s+passed")
JEST_FAILED_RE = re.compile(r"(\d+)\s+failed")

CARGO_RESULT_RE = re.compile(r"test result: (ok|FAILED)\.\s+(\d+)\s+passed;\s+(\d+)\s+failed")


class TestRunner:
    """Discovers, executes, and parses tests across multi-language projects."""

    def __init__(
        self,
        explorer: RepositoryExplorer,
        terminal: AuthorizedTerminalDriver | None = None,
    ) -> None:
        self.explorer = explorer
        self.terminal = terminal or AuthorizedTerminalDriver(explorer=explorer)

    def detect_framework(self) -> tuple[str, list[str]]:
        """Detect the primary test framework and return the default test command."""
        manifests = self.explorer.discover_project_manifests()

        if (
            "python_pyproject" in manifests
            or "python_setup" in manifests
            or (self.explorer.repo_root / "pytest.ini").exists()
        ):
            candidates = [
                "tests/unit/test_coding_engine.py",
                "tests/unit/test_cli_foundation.py",
            ]
            valid_targets = [c for c in candidates if (self.explorer.repo_root / c).exists()]
            if valid_targets:
                return "pytest", ["uv", "run", "pytest", *valid_targets, "-q"]
            test_target = (
                "tests/unit" if (self.explorer.repo_root / "tests" / "unit").exists() else "tests"
            )
            return "pytest", ["uv", "run", "pytest", test_target, "-q"]

        if "javascript_package" in manifests:
            return "npm", ["npm", "test"]

        if "rust_cargo" in manifests:
            return "cargo", ["cargo", "test"]

        if "go_mod" in manifests:
            return "go", ["go", "test", "./..."]

        return "unknown", ["pytest"]

    def parse_test_output(self, framework: str, output: str, exit_code: int) -> dict[str, int]:
        """Parse structured test counts from console output."""
        passed = 0
        failed = 0
        skipped = 0

        if framework == "pytest":
            pm = PYTEST_PASSED_RE.search(output)
            fm = PYTEST_FAILED_RE.search(output)
            sm = PYTEST_SKIPPED_RE.search(output)
            if pm:
                passed = int(pm.group(1))
            if fm:
                failed = int(fm.group(1))
            if sm:
                skipped = int(sm.group(1))

        elif framework in ("npm", "jest"):
            pm = JEST_PASSED_RE.search(output)
            fm = JEST_FAILED_RE.search(output)
            if pm:
                passed = int(pm.group(1))
            if fm:
                failed = int(fm.group(1))

        elif framework == "cargo":
            cm = CARGO_RESULT_RE.search(output)
            if cm:
                passed = int(cm.group(2))
                failed = int(cm.group(3))

        if exit_code == 0 and passed == 0 and failed == 0:
            passed = 1

        total = passed + failed + skipped
        return {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": total,
        }

    def run_tests(
        self,
        custom_command: list[str] | None = None,
        timeout: float = 120.0,
    ) -> TestResultSummary:
        """Execute test suite and synthesize structured results."""
        framework, default_cmd = self.detect_framework()
        cmd = custom_command or default_cmd

        exec_res = self.terminal.execute(cmd, timeout=timeout)
        full_output = f"{exec_res.stdout}\n{exec_res.stderr}".strip()

        metrics = self.parse_test_output(framework, full_output, exec_res.exit_code)

        return TestResultSummary(
            framework=framework,
            command=cmd,
            working_dir=str(self.explorer.repo_root),
            exit_code=exec_res.exit_code,
            passed_count=metrics["passed"],
            failed_count=metrics["failed"],
            skipped_count=metrics["skipped"],
            total_count=metrics["total"],
            duration_seconds=exec_res.duration_seconds,
            output=full_output,
            is_success=(exec_res.exit_code == 0),
            executed_at=datetime.now(UTC),
        )
