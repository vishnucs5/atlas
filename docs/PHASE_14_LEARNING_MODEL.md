# ATLAS Phase 14 Experience Learning System Specification
## Structured Pattern Storage, Provenance & Memory Integrity

---

## 1. Experience Record Schema

The Experience Learning System transforms raw execution events into structured, immutable experience records:

```python
class ExperienceRecord:
    experience_id: str
    tenant_id: str
    task_category: str  # browser, desktop, coding, document, data, enterprise
    context_fingerprint: str
    observed_facts: list[str]  # Objective events and deterministic observations
    generated_recommendations: list[str]  # Model-derived suggestions
    outcome: str  # SUCCESS, FAILURE, PARTIAL
    evaluation_score: float
    confidence: float
    source_task_id: str
    provenance_hash: str
    is_verified: bool  # False until validated by independent evaluator
    created_at: float
    version: int
```

---

## 2. Strict Separation of Facts from Recommendations

To prevent hallucinated advice from poisoning future tasks:
- **Observed Facts**: Verifiable runtime occurrences (e.g. `Element #submit-btn became disabled after click`, `HTTP 429 received from endpoint X`).
- **Generated Recommendations**: Advisory guidance (e.g. `Wait 2.5s before polling status endpoint`).
- **Memory Integrity Invariant**: Unverified recommendations (`is_verified == False`) are never injected as authoritative policy or instructions into the planner.
