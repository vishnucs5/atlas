# ATLAS Phase 12 Architecture Specification
## Kubernetes-Native Orchestration & Multi-Cluster Edge Execution

---

## 1. High-Level Architectural Model

ATLAS Phase 12 decouples **infrastructure lifecycle management** from **autonomous task execution**.

```
                   +------------------------------------------------+
                   |            GLOBAL ATLAS CONTROL PLANE          |
                   |  Global Task Scheduler & Multi-Cluster Routing |
                   +-----------------------+------------------------+
                                           |
         +---------------------------------+---------------------------------+
         |                                 |                                 |
         v                                 v                                 v
+-----------------------+       +-----------------------+       +-----------------------+
|  Primary K8s Cluster  |       |  Secondary K8s Cluster|       |  Edge Execution Zone  |
| (us-east / Production)|       | (eu-west / Failover)  |       | (Industrial/Branch)   |
|                       |       |                       |       |                       |
|  +-----------------+  |       |  +-----------------+  |       |  +-----------------+  |
|  | ATLAS Operator  |  |       |  | ATLAS Operator  |  |       |  | Edge Gateway    |  |
|  +--------+--------+  |       |  +--------+--------+  |       |  | (Outbound TLS)  |  |
|           |           |       |           |           |       |  +--------+--------+  |
|     +-----+-----+     |       |     +-----+-----+     |       |           |           |
|     |     |     |     |       |     |     |     |     |       |     +-----+-----+     |
|     v     v     v     |       |     v     v     v     |       |     v     v     v     |
|    API Super Worker   |       |    API Super Worker   |       |   Edge  Edge  Windows |
|    Pods Pods  Pods    |       |    Pods Pods  Pods    |       |   Linux Linux Desktop |
+-----------------------+       +-----------------------+       +-----------------------+
```

---

## 2. Component Architecture & Responsibilities

### 2.1 ATLAS Kubernetes Operator (`atlas-operator`)
- **Authority**: Manages Kubernetes resources (Deployments, StatefulSets, Services, ConfigMaps, Secrets, HPAs, NetworkPolicies).
- **Non-Authority**: Does NOT execute user tasks, inspect task prompts, or schedule agent actions.
- **Reconciliation Engine**: Idempotently reconciles desired state defined in CRDs against live cluster state.
- **Drift Detection**: Automatically restores modified Kubernetes resources to their declared configuration.
- **Safe Lifecycle**: Utilizes finalizers to guarantee clean worker drain and stateful asset preservation before resource deletion.

### 2.2 Workload-Aware Autoscaler
- Unlike standard Horizontal Pod Autoscalers that scale strictly on average CPU or memory utilization, the ATLAS Autoscaler monitors:
  1. `queue_depth`: Number of unassigned queued tasks matching the worker pool's capability profile.
  2. `pending_assignments`: Tasks waiting for worker acceptance.
  3. `worker_utilization`: Active execution concurrency vs maximum worker capacity.
  4. `sla_urgency`: Remaining time before task execution deadlines.
  5. `tenant_quotas`: Enforces maximum concurrent worker limits per tenant.
- **Anti-Flapping Architecture**: Configurable scale-up cooldown (default 30s) and scale-down cooldown (default 300s) with max scale step boundaries.

### 2.3 Multi-Cluster Orchestrator
- **Federated Topology**: Central control plane connects to registered clusters via mutual TLS or authenticated ServiceAccount tokens.
- **Dynamic Inventory**: Aggregates capacity, available GPUs, region, and network latency.
- **Placement Policy**:
  - `Capabilities`: Routes tasks requiring specialized runtimes (e.g. Windows GUI, specific GPU models) to capable clusters.
  - `Data Locality`: Prefers clusters in the same cloud region as external data stores or CRM instances.
  - `Tenant Isolation`: Maps tenant tiers to dedicated or partitioned clusters.
- **Cluster Failover**: Heartbeat loss triggers controlled worker reassignment with monotonic fencing tokens.

### 2.4 Edge Execution Gateway
- **Zero Inbound Ports**: Edge nodes initiate outbound WebSocket/TLS connections to the central gateway over HTTPS (port 443).
- **Reverse Command Channel**: The gateway multiplexes task assignments, heartbeats, and cancellations across the established outbound connection.
- **Offline Durability**: Edge workers maintain a local SQLite buffer. If network connectivity drops during execution, the worker completes the task, buffers results and evidence, and synchronizes deterministically upon reconnection.
- **Remote Revocation**: Control plane can revoke edge enrollment instantly; the gateway forcibly terminates leases and disconnects the node.

---

## 3. Storage & Persistence Invariants

1. **Stateful Services**: PostgreSQL and Redis are managed via external managed services (RDS, Cloud SQL) or dedicated StatefulSets with PersistentVolumeClaims.
2. **Dual-Database Support**: Transparent support for PostgreSQL (production) and SQLite (edge / local worker buffer).
3. **Write-Through Caching**: All tenant models, policies, and worker records persist immediately to the database before acknowledging state transitions.
