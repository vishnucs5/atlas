# ATLAS Independent Code Review and Adversarial QA

## 1. The Necessity of Independent Review

In autonomous developer environments, self-evaluating agents exhibit confirmation bias, repeatedly claiming success even when tests fail or syntax is broken. 

The **Action Firewall & Verification Invariant** mandates that an independent agent (`IndependentCodeReviewer`) must objectively audit deliverables before a task can be reported complete.

---

## 2. Review Inspection Dimensions

The `IndependentCodeReviewer` inspects six independent dimensions:

1. **Requirements Satisfaction**:
   Compares the decomposed task objective against the actual produced deliverables and completed subtask nodes.
2. **Unified Diff Inspection**:
   Directly parses unified diffs across all modified files. Verifies that changes are clean, syntactically coherent, and free of leftover debug scaffolding.
3. **Automated Test Evidence**:
   Verifies that a test or QA node was executed and achieved `PASSED` status with zero failures. Rejects deliverables if tests were skipped or failed.
4. **Security Implications**:
   Scans diff text with regex and heuristics for:
   - Hardcoded API keys, tokens, or passwords (`SECRET_REGEX`).
   - Unsafe arbitrary execution patterns (`os.system`, `subprocess.Popen(shell=True)`, `eval()`, `exec()`).
   - Potential prompt injection strings in comments or strings.
5. **Architectural Boundaries**:
   Scans imports to verify that core packages do not import non-core or external dependencies (preserving the Zero-Dependency Core invariant).
6. **Regression Risk Analysis**:
   Verifies that modifications do not delete files or remove existing test assertions without justification.

---

## 3. Actionable Findings and Rejection Protocol

Superficial rejections (e.g. "code looks bad") are prohibited. When a review fails, the reviewer produces structured `CodeReviewFinding` entries:

```python
class CodeReviewFinding(BaseModel):
    finding_id: str
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    category: str  # "REQUIREMENTS", "DIFF", "TESTS", "SECURITY", "ARCHITECTURE"
    file_path: str
    line_number: int | None
    issue: str
    remediation: str
```

### Review Outcomes:
- **`APPROVED`**: All criteria satisfied; tests passed; security clean. Supervisor marks execution successful.
- **`REJECTED`**: One or more `CRITICAL` or `HIGH` findings detected. Supervisor raises `ReviewRejectionError` with the exact remediation instructions.
