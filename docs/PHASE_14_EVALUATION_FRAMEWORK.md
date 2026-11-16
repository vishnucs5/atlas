# ATLAS Phase 14 Evaluation Framework Specification
## Objective Evidence-Driven Task Outcome Evaluation

---

## 1. Principles of Task Evaluation

1. **Evidence-Based, Not LLM Self-Reported**: An LLM agent claiming "I successfully placed the order" is never accepted as proof of success. The Task Evaluation Engine verifies concrete post-condition evidence: HTTP receipts, signed database rows, screenshot state diffs, or file hashes.
2. **Multi-Faceted Rubrics**: Tasks are scored on a normalized scale $[0.0, 1.0]$ across multiple orthogonal dimensions:
   - **Functional Correctness** ($\omega = 0.40$): Were all explicit task requirements satisfied with deterministic verification evidence?
   - **Efficiency** ($\omega = 0.20$): Ratio of observed execution duration and token count against standard baselines.
   - **Reliability & Recovery** ($\omega = 0.20$): Penalty for high retry counts, unexpected exceptions, or recovery loop triggers.
   - **Policy & Compliance** ($\omega = 0.20$): Zero unhandled policy denials, zero firewall rejections, zero unauthorized access attempts.

---

## 2. Evaluation Data Model

```python
class TaskEvaluationResult:
    evaluation_id: str
    task_id: str
    tenant_id: str
    timestamp: float
    is_completed: bool
    is_false_success: bool  # Agent claimed success, but verification evidence failed
    overall_score: float  # [0.0, 1.0]
    functional_score: float
    efficiency_score: float
    reliability_score: float
    compliance_score: float
    verification_evidence_refs: list[str]
    failure_reasons: list[str]
    metrics: dict[str, float]  # duration_sec, token_cost_usd, retry_count, recovery_count
```

### 2.1 False Success Detection
If `task.status == COMPLETED` but `len(verification_evidence_refs) == 0` or verified post-conditions do not match expected states, `is_false_success` is flagged as `True` and the overall evaluation score is clamped to $0.0$.
