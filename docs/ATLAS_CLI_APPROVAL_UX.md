# ATLAS CLI — Action Firewall Approval UX Specification

## 1. Governance Principles & Invariants

Autonomous agents interacting with critical developer workstations or production clusters must never execute destructive or sensitive actions without explicit authorization.

### Mandatory UX Invariants
1. **No Vague Prompts**: The CLI strictly rejects generic prompts such as *"Allow agent to continue? [Y/N]"*. Every approval request must present the exact action details.
2. **Mandatory Action Metadata**:
   - **Operation**: The exact qualified action type (e.g. `file.modify`, `terminal.execute`, `git.commit`).
   - **Target**: Specific file path, hostname, or executable identifier.
   - **Parameters**: Structured parameter table (e.g. SHA-256 pre-hash, command argument vector, byte size).
   - **Risk Level**: Clear visual indicator (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`).
   - **Scope**: Boundary of impact (`workspace`, `network`, `system`).
   - **Duration Cap**: Maximum execution timeout for the authorized operation.
   - **Policy Version**: Declarative version string of the evaluating policy rule.
3. **Action Tampering Invalidation**: If the agent or tool alters any parameter of an action after authorization was requested, the prior approval token is instantly invalidated.
4. **Presentation Engine Separation**: The CLI and TUI are unauthorized to grant permissions directly; they must submit operator decisions to the ATLAS approval engine (`AtlasClient.grant_approval()` / `ActionFirewall`).

---

## 2. Standard Approval Card Visual Specification

```
┌─[ ACTION FIREWALL AUTHORIZATION REQUEST ]──────────────────────────────────────
│ Request ID:      appr_a9b8c7d6e5f4
│ Operation:       file.modify
│ Target:          src/auth/jwt.py
│ Risk Level:      [CRITICAL]
│ Scope:           workspace
│ Duration Cap:    60s
│ Policy Version:  1.0
│ Policy Context:  Modifies authentication credentials and cryptographic tokens.
├─[ EXACT PARAMETERS ]──────────────────────────────────────────────────────────
│   {
│     "before_hash": "c1f7a80b35f7267365e45934a0f99f8af09f027015a67dd3005e08b6486b7e86",
│     "new_size": 2450,
│     "lines_added": 14,
│     "lines_removed": 3
│   }
└──────────────────────────────────────────────────────────────────────────────
Authorize exact action? [Yes / No / Skip]:
```

---

## 3. Interactive Decision Flow

1. **Operator Review**: The operator reviews the formatted card in Minimal Mode or the TUI Approvals panel.
2. **Decision Input**:
   - `[Y]es`: Prompts for optional justification audit note, then calls `client.grant_approval(req_id, reason)`.
   - `[N]o`: Prompts for denial rationale, then calls `client.deny_approval(req_id, reason)`.
   - `[S]kip`: Preserves the request in `PENDING` state for subsequent review.
3. **Audit Ledger Recording**: The decision and justification are cryptographically recorded in the storage ledger and emitted as `APPROVAL_GRANTED` or `APPROVAL_DENIED` events.
