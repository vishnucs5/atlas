# ATLAS Phase 14 Architecture Specification
## Autonomous Self-Improvement, Evaluation & Adaptive Intelligence Platform

---

## 1. System Architecture & Component Interaction

Phase 14 introduces the `atlas-adaptive` package as a closed-loop evaluation, learning, and controlled optimization layer on top of the existing ATLAS control plane:

```mermaid
flowchart TD
    subgraph Execution["ATLAS Execution & Control Plane"]
        Task["Task Lifecycle & Execution Events"] --> Evidence["Deterministic Execution Evidence (Receipts, Artifacts, Traces)"]
    end

    subgraph EvaluationLayer["Evaluation & Analytics"]
        Evidence --> Eval["Task Evaluation Engine (evaluator.py)"]
        Eval --> Fail["Failure Analysis Engine (failure_analyzer.py)"]
        Eval --> Exp["Experience Learning System (experience.py)"]
        Eval --> AgentAn["Agent Performance Intelligence (agent_analytics.py)"]
        Eval --> Regr["Regression Intelligence (regression.py)"]
    end

    subgraph OptimizationLayer["Optimization & Experimentation"]
        Exp --> Opt["Strategy Optimization Engine (optimizer.py)"]
        Fail --> Opt
        Opt --> Cand["Improvement Candidates (Strategies, Prompts, Routing)"]
        Cand --> ExpEngine["Automated Sandboxed Experimentation (experimentation.py)"]
        ExpEngine --> Stat["Statistical Validation & Baseline Comparison"]
    end

    subgraph GovernanceLayer["Safety Governance & Promotion"]
        Stat --> Gov["Safety Governor (governor.py)"]
        Gov -->|"Check Protected Boundaries (Firewall, Auth, Code)"| Rej["Reject Unauthorized Changes"]
        Gov -->|"Risk Scoring & Approval"| Prom["Promotion Lifecycle (promotion.py)"]
        Prom -->|"Canary Staged Deployment"| Router["Adaptive Model Router (adaptive_router.py)"]
        Prom -->|"Knowledge Update"| Know["Controlled Knowledge Evolution (knowledge.py)"]
        Prom -->|"Rollback Trigger"| Rollback["Instant Version Rollback"]
    end
```

---

## 2. Immutable Boundaries & Safety Invariants

The fundamental architectural principle of Phase 14 is **bounded adaptation**:

1. **Mutable Domain**:
   - Strategy parameters (planning depth, retry backoffs, fallback order).
   - Adaptive model routing weights (cost/latency trade-offs).
   - Knowledge artifacts and prompt examples.
   - Tool selection heuristics within approved tool catalogs.
2. **Strictly Immutable Domain (Safety Governor Protected)**:
   - Action Firewall rules and policy engine.
   - Core authorization, authentication, and token verification.
   - Tenant isolation and cross-tenant boundary controls.
   - Credential and secret management.
   - Production source code (`packages/atlas-*`, `apps/*`).
   - Audit trail persistence and integrity.

Any candidate modification targeting the immutable domain triggers immediate rejection with `ProtectedComponentModificationError` and emits an alert to the security audit ledger.
