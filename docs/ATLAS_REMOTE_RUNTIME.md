# ATLAS Remote Runtime & Federation Architecture

## 1. Overview

ATLAS CLI can delegate intensive computational tasks (e.g. heavy model inference, distributed test suites, large repository builds) to remote worker nodes and federation gateways using the `atlas-federation` protocol.

The `RemoteRuntimeClient` manages remote discovery, session leasing, event streaming, and failure recovery.

```
┌─────────────────┐           Secure HTTPS / mTLS           ┌────────────────────────┐
│    ATLAS CLI    │────────────────────────────────────────>│   Federation Gateway   │
│ (Local Engine)  │<────────────────────────────────────────│    (Remote Cluster)    │
└────────┬────────┘             Streamed Events             └───────────┬────────────┘
         │                                                              │
         │ Acquire Lease                                                │ Dispatch Task
         ▼                                                              ▼
┌─────────────────┐                                         ┌────────────────────────┐
│  Session Lease  │                                         │ Remote Worker Agents   │
│  (Token Masked) │                                         │ (GPU Nodes, Sandboxes) │
└─────────────────┘                                         └────────────────────────┘
```

---

## 2. Remote Node Discovery & Capability Advertising

Remote nodes advertise their available capabilities, agents, supported task categories, and latency:
- Advertised visibility scopes (`PRIVATE`, `ORGANIZATION`, `FEDERATION`, `PUBLIC`).
- CLI client queries nodes matching required capabilities (e.g. `coding`, `testing`, `machine-learning`).
- Redaction of sensitive internal endpoints or credentials in advertised metadata.

---

## 3. Session Leasing & Token Security

Delegating work requires acquiring an explicit `RemoteSessionLease`:
1. The lease establishes an authorized execution window on a specific remote node.
2. The authentication token is masked in memory and logs (`auth_token_masked`) to prevent secret exposure.
3. Leases feature bounded lifetimes (`expires_at`); expired leases are automatically invalidated.
4. Finished tasks trigger `release_session_lease()`, returning worker capacity to the cluster pool.

---

## 4. Event Streaming & Connection Recovery

Execution progress is streamed back to the CLI:
- Events include `task_started`, `tool_execution`, `output_chunk`, `completed`, and `error`.
- Events are buffered locally and retrieved via non-blocking polling (`poll_events()`).
- **Resilient Recovery**: In the event of network disruption or terminal disconnect, the client reconnects using the active `lease_id` via `reconnect_and_resume()`. If the lease is still valid, task execution resumes seamlessly without re-running completed steps.
