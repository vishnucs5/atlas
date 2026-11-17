# ATLAS Phase 16 Human Approval Model

Specifies human approval governance, parameter hashing, separation of duties, and multi-person quorums.

## 1. Governance Invariants
1. **Immutable Binding**: Approvals are cryptographically bound to process instance ID, task ID, action, target resource, and parameter hash.
2. **Anti-Tampering**: Mutating parameters between request and decision triggers `ParameterTamperedError`.
3. **Separation of Duties (SoD)**: The requesting entity cannot approve its own action (`SeparationOfDutiesViolationError`).
4. **Quorums**: Configurable multi-approver requirements (e.g. 2 approvals for capital expenditures).
5. **Timeouts**: Approvals past `expires_at` are automatically invalidated (`ApprovalExpiredError`).
