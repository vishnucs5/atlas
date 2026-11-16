# ATLAS Phase 14 Automated Experimentation Specification
## Isolated Trials, Statistical Benchmarking & Shadow Evaluation

---

## 1. Experimentation Framework Invariants

1. **Sandboxed Worker Isolation**: Candidate strategies run in ephemeral, isolated sandboxes without access to production credentials, databases, or live customer sessions.
2. **Deterministic Benchmark Scenarios**: Experiments are evaluated across fixed, versioned test datasets to eliminate variance.
3. **Repeated Trials & Statistical Power**: Candidates must execute a minimum number of trials ($N \ge 5$) before claiming statistically significant improvement.
4. **Hard Resource Limits & Cancellation**: Experiments enforce timeout ceilings (e.g. 60s per trial) and maximum token/cost budgets. Runaway trials are immediately aborted.

---

## 2. Experiment Lifecycle & Statistical Metrics

```python
class ExperimentDefinition:
    experiment_id: str
    candidate_strategy_id: str
    baseline_strategy_id: str
    benchmark_suite_id: str
    min_trials: int = 5
    max_trials: int = 20
    max_cost_usd: float = 5.0
    timeout_sec: float = 120.0
```

- **Metrics Tracked**:
  - Delta Success Rate: $\Delta_{success} = \bar{S}_{candidate} - \bar{S}_{baseline}$
  - Delta Latency: $\Delta_{latency} = \bar{L}_{candidate} - \bar{L}_{baseline}$
  - Delta Cost: $\Delta_{cost} = \bar{C}_{candidate} - \bar{C}_{baseline}$
- **Significance Test**: Student's t-test or non-parametric Mann-Whitney U test with $p < 0.05$. No improvement claim is accepted without meeting this statistical barrier.
