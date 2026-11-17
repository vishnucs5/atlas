"""Independent code reviewer inspecting diffs, test evidence, security, and architectural invariants."""

import re
import uuid

from atlas_core.contracts.coding import UnifiedDiff
from atlas_core.contracts.graph import NodeStatus, TaskGraph
from pydantic import BaseModel, ConfigDict, Field

from atlas_orchestration.memory import SharedMemoryEngine
from atlas_orchestration.reviewer import IndependentReviewer, ReviewVerdict

SECRET_REGEX = re.compile(
    r"""(?i)(?:api_key|token|secret|password)\s*=\s*['"][a-zA-Z0-9_\-\.]{8,}['"]"""
)
UNSAFE_EXEC_REGEX = re.compile(
    r"""(?i)\b(?:os\.system|subprocess\.Popen\(.*shell\s*=\s*True|eval\(|exec\()"""
)
INJECTION_REGEX = re.compile(
    r"""(?i)\b(?:ignore\s+previous\s+instructions|bypass\s+action\s+firewall)\b"""
)


class CodeReviewFinding(BaseModel):
    """Specific actionable finding identified by the independent code reviewer."""

    model_config = ConfigDict(validate_assignment=True)

    finding_id: str
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    category: str  # "REQUIREMENTS", "DIFF", "TESTS", "SECURITY", "DEPENDENCIES", "ARCHITECTURE"
    file_path: str = ""
    line_number: int | None = None
    issue: str
    remediation: str


class CodeReviewResult(BaseModel):
    """Audit assessment emitted by the independent code reviewer."""

    model_config = ConfigDict(validate_assignment=True)

    verdict: ReviewVerdict
    summary: str
    actionable_findings: list[CodeReviewFinding] = Field(default_factory=list)
    inspected_diff_lines: int = 0
    tests_verified: bool = False
    security_clean: bool = True
    architecture_clean: bool = True


class IndependentCodeReviewer(IndependentReviewer):
    """Independent reviewer conducting adversarial, evidence-backed inspection of code deliverables."""

    def __init__(self, memory: SharedMemoryEngine) -> None:
        super().__init__(memory=memory)

    def review_code_deliverables(
        self,
        graph: TaskGraph,
        diffs: list[UnifiedDiff] | None = None,
        require_tests: bool = True,
        disallowed_imports: list[str] | None = None,
    ) -> CodeReviewResult:
        """Perform deterministic review across requirements, diffs, tests, security, and architecture."""
        findings: list[CodeReviewFinding] = []
        total_diff_lines = 0
        tests_verified = False
        security_clean = True
        architecture_clean = True

        completed_nodes = [n for n in graph.nodes.values() if n.status == NodeStatus.COMPLETED]

        # 1. Inspect Requirements & Node Deliverables
        if not completed_nodes:
            findings.append(
                CodeReviewFinding(
                    finding_id=f"f_{uuid.uuid4().hex[:6]}",
                    severity="CRITICAL",
                    category="REQUIREMENTS",
                    issue="No completed subtasks found in execution graph.",
                    remediation="Execute implementation tasks before requesting code review.",
                )
            )

        # 2. Inspect Test Evidence
        test_nodes = [
            n
            for n in completed_nodes
            if "test" in n.name.lower() or "qa" in n.name.lower() or "verify" in n.name.lower()
        ]
        if require_tests:
            if not test_nodes:
                findings.append(
                    CodeReviewFinding(
                        finding_id=f"f_{uuid.uuid4().hex[:6]}",
                        severity="HIGH",
                        category="TESTS",
                        issue="No testing or QA verification node found in completed deliverables.",
                        remediation="Add an automated testing task and verify test execution succeeds.",
                    )
                )
            else:
                for tn in test_nodes:
                    output = tn.output or {}
                    results = output.get("results", {})
                    if results.get("verdict") == "PASSED" or output.get("verdict") == "PASSED":
                        tests_verified = True
                    else:
                        findings.append(
                            CodeReviewFinding(
                                finding_id=f"f_{uuid.uuid4().hex[:6]}",
                                severity="CRITICAL",
                                category="TESTS",
                                issue=f"Test verification node '{tn.node_id}' did not achieve PASSED status.",
                                remediation="Fix failing tests and re-run suite until 100% green.",
                            )
                        )

        # 3. Inspect Actual Diffs (Unified Diff Inspection)
        if diffs:
            for diff in diffs:
                total_diff_lines += len(diff.raw_diff.splitlines())
                f_path = diff.patches[0].target_path if diff.patches else ""

                # Security: scan diff text for secrets, unsafe execution, and prompt injections
                if SECRET_REGEX.search(diff.raw_diff):
                    security_clean = False
                    findings.append(
                        CodeReviewFinding(
                            finding_id=f"f_{uuid.uuid4().hex[:6]}",
                            severity="CRITICAL",
                            category="SECURITY",
                            file_path=f_path,
                            issue="Hardcoded API key, credential, or password detected in diff.",
                            remediation="Move credential to environment variable or secret manager.",
                        )
                    )

                if UNSAFE_EXEC_REGEX.search(diff.raw_diff):
                    security_clean = False
                    findings.append(
                        CodeReviewFinding(
                            finding_id=f"f_{uuid.uuid4().hex[:6]}",
                            severity="CRITICAL",
                            category="SECURITY",
                            file_path=f_path,
                            issue="Unsafe arbitrary execution pattern (os.system/eval/shell=True) in diff.",
                            remediation="Use AuthorizedTerminalDriver or safe structured argument vectors.",
                        )
                    )

                if INJECTION_REGEX.search(diff.raw_diff):
                    security_clean = False
                    findings.append(
                        CodeReviewFinding(
                            finding_id=f"f_{uuid.uuid4().hex[:6]}",
                            severity="HIGH",
                            category="SECURITY",
                            file_path=f_path,
                            issue="Potential prompt injection payload identified in code comments/diff.",
                            remediation="Remove adversarial prompt injection string from source file.",
                        )
                    )

                # Architecture: scan for prohibited imports (e.g. core importing external packages)
                if disallowed_imports:
                    for dis_imp in disallowed_imports:
                        if (
                            f"import {dis_imp}" in diff.raw_diff
                            or f"from {dis_imp}" in diff.raw_diff
                        ):
                            architecture_clean = False
                            findings.append(
                                CodeReviewFinding(
                                    finding_id=f"f_{uuid.uuid4().hex[:6]}",
                                    severity="CRITICAL",
                                    category="ARCHITECTURE",
                                    file_path=f_path,
                                    issue=f"Prohibited import '{dis_imp}' violates architecture boundaries.",
                                    remediation=f"Remove import '{dis_imp}' to preserve modular separation.",
                                )
                            )

        # 4. Determine Verdict
        has_critical = any(f.severity in ("CRITICAL", "HIGH") for f in findings)
        verdict = ReviewVerdict.REJECTED if has_critical else ReviewVerdict.APPROVED

        summary = (
            f"Independent review {verdict.value}. "
            f"{len(findings)} findings ({sum(1 for f in findings if f.severity in ('CRITICAL', 'HIGH'))} blocking). "
            f"Inspected {total_diff_lines} diff lines across {len(diffs or [])} files."
        )

        return CodeReviewResult(
            verdict=verdict,
            summary=summary,
            actionable_findings=findings,
            inspected_diff_lines=total_diff_lines,
            tests_verified=tests_verified,
            security_clean=security_clean,
            architecture_clean=architecture_clean,
        )
