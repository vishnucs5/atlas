# ATLAS Phase 7 Risk Register: Multi-Agent Intelligence & Orchestration

**Document Version:** 1.0.0  
**Phase:** Phase 7 — Multi-Agent Intelligence & Autonomous Orchestration  
**Status:** Active  

---

## 1. Risk Evaluation & Mitigation Matrix

| Risk ID | Category | Risk Description | Severity | Likelihood | ATLAS Mitigation Strategy | Subsystem Owner |
| :--- | :--- | :--- | :---: | :---: | :--- | :--- |
| **RSK-MA-01** | Architecture | Circular Delegation Deadlock (Agent A delegates to B, B to C, C to A) | HIGH | MEDIUM | Track immutable delegation path call-stack on every message. Reject recursion beyond configured `max_delegation_depth` (default 3) and raise `CircularDelegationError`. | `AgentMessageRouter` |
| **RSK-MA-02** | Security | Cross-Task Snooping & Memory Leakage across tenant/task boundaries | HIGH | LOW | Strict tenant/task scoping in `SharedMemoryEngine`. Access control enforcement rejects read/write across disparate root `task_id` spaces. | `SharedMemoryEngine` |
| **RSK-MA-03** | Security | Prompt Injection / Policy Hijack via Untrusted Memory Content | CRITICAL | MEDIUM | Untrusted content flag (`is_untrusted=True`) attached to all external DOM/data extracts. Untrusted memory entries are partitioned in context prompts and forbidden from mutating policy rules. | `SharedMemoryEngine`, `ActionFirewall` |
| **RSK-MA-04** | Distributed Systems | Worker/Specialist Crash or Unresponsive State during subtask execution | HIGH | MEDIUM | Monotonic heartbeats and lease expiration timeouts. Recovery manager detects expired leases, recovers checkpoint, and safely reassigns subtask. | `MultiAgentRecoveryManager` |
| **RSK-MA-05** | Reliability | Blind Duplicate Execution of Non-Idempotent External Actions on Failure | CRITICAL | LOW | Action ledger deduplication and strict `UNKNOWN` state safety. Non-idempotent actions cannot be retried without reconciliation or operator approval. | `ActionLedger`, `MultiAgentRecoveryManager` |
| **RSK-MA-06** | Performance | Task Graph Cycle / Infinite Parallel Fan-Out | HIGH | LOW | Cycle detection (topological sort via Kahn's algorithm) executed prior to DAG dispatch. Maximum parallel nodes bounded by supervisor concurrency limits. | `TaskGraphEngine`, `AgentSupervisor` |
| **RSK-MA-07** | Economic | Model Token & Cost Budget Runaway in Multi-Agent Loops | HIGH | MEDIUM | Hierarchical budget enforcement: global task budget caps child specialist budgets. Exceeding token/cost budget halts execution and triggers review. | `AgentRegistry`, `ModelRouter` |
| **RSK-MA-08** | Governance | Premature Task Completion based on Agent Self-Reporting | HIGH | MEDIUM | Mandatory independent verification gate (`IndependentReviewer`). Task cannot complete without deterministic verification of outputs and evidence. | `IndependentReviewer` |

---

## 2. Contingency & Escalation Protocols

1. **Cycle Detection Triggered:**
   - Immediately abort DAG planning; transition task to `FAILED` or trigger structured replanning.
   - Emit `PLAN_REJECTED` event with cycle path diagnostics.
2. **Lease Expiration / Specialist Crash:**
   - Attempt automatic reassignment to a healthy specialist with matching capability.
   - If no healthy specialist exists or retry limit is exceeded, pause task in `WAITING_FOR_ENVIRONMENT` and alert operator.
3. **Budget Exhaustion:**
   - Terminate active child branches cleanly, preserve partial artifacts in checkpoint, and transition task to `PAUSED` with reason `BUDGET_EXHAUSTED`.
4. **Untrusted Memory Collision:**
   - Drop untrusted instruction overrides silently, log security audit event `UNTRUSTED_CONTENT_SANITIZED`.
