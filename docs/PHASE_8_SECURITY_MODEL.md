# ATLAS Phase 8 Security Model: Supply-Chain Protection & Sandboxed Execution

## 1. Threat Model & Security Principles

The workflow marketplace introduces code, workflow graphs, and configurations from external or organizational publishers into the ATLAS platform. The threat model follows strict zero-trust assumptions:

> **Fundamental Principle:** A cryptographic signature proves package integrity and publisher key possession. It does NOT prove that the package logic or model instructions are safe.

```
 +--------------------------------------------------------------------------+
 |                      Supply Chain Security Funnel                        |
 +--------------------------------------------------------------------------+
 | 1. Package Tamper Check     | SHA-256 Digest against Manifest Checksums  |
 | 2. Publisher Identity       | Cryptographic Signature & Revocation Audit |
 | 3. Manifest Validation      | Pydantic Strict Schema & Range Validation  |
 | 4. Permission Audit         | Least Privilege & Explicit Firewall Review |
 | 5. Content Sanitization     | Untrusted Instruction Injection Shield     |
 | 6. Sandboxed Execution      | Context-Restricted Skill & Driver Boundary |
 | 7. Independent Review       | Deterministic Post-Execution Evidence Audit|
 +--------------------------------------------------------------------------+
```

---

## 2. Attack Vectors & Mitigations

| Threat Vector | STRIDE Classification | Impact | ATLAS Defense / Mitigation |
|---|---|---|---|
| **Package Tampering / MITM** | Tampering | Malicious node injected into package archive | SHA-256 digest sidecar verified for every file. Any mismatched hash immediately rejects extraction. |
| **Compromised Publisher Key** | Spoofing | Adversary publishes malicious package version | Central Publisher Revocation Ledger. Revoking a publisher key blocks all installations and runtime execution. |
| **Privilege Escalation** | Elevation of Privilege | Package requests elevated driver permissions without review | Explicit permission declarations evaluated at install-time. Workflow cannot exceed installed permissions. |
| **Indirect Prompt Injection** | Tampering / Information Disclosure | Package instructions or data trick LLM into unauthorized actions | `SharedMemoryEngine` flags all package metadata and workflow prompts as `is_untrusted=True`. |
| **Infinite Loop / Resource Exhaustion** | Denial of Service | Malicious DAG consumes cluster tokens or threads | Cycle detection in graph engine (`CyclicDependencyError`) and hard budget bounds (`AgentBudgetExhaustedError`). |
| **Non-Idempotent Action Replay** | Repudiation / Tampering | Worker crash triggers duplicate payment or write | Action ledger requires operator reconciliation for `UNKNOWN` state (`NonIdempotentActionUncertaintyError`). |
| **Cross-Tenant Package Leakage** | Information Disclosure | Private organizational package accessed by unauthorized tenant | Multi-tenant isolation barriers in `MarketplaceRegistry` and `SharedMemoryEngine`. |

---

## 3. Sandboxing & Runtime Isolation

1. **No Control Plane Contamination**:
   - Workflows are data descriptions (JSON/Pydantic DAG models), never arbitrary executable Python scripts.
   - Skills run inside a constrained `SkillContext` that prohibits direct access to control plane internals, process execution, or sockets.
2. **Action Firewall Enclosure**:
   - Any browser navigation, native desktop action, or system command dispatched during workflow execution must be pre-authorized in the package's `permissions` declaration and evaluated by `ActionFirewall.evaluate()`.
3. **Audit Evidence Requirement**:
   - No workflow can transition to `COMPLETED` without verified output deliverables confirmed by `IndependentReviewer`.
