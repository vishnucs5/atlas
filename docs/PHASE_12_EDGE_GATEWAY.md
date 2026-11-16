# ATLAS Phase 12 Edge Execution Gateway Specification
## Remote Workers & Constrained Edge Infrastructure

---

## 1. Network Topology & Invariant

```
[ Edge Worker / Field Device ]
          |
          | Outbound HTTPS/WSS (Port 443)
          | Mutual TLS / Cryptographic Token
          v
[ Reverse Proxy / Ingress ]
          |
          v
[ ATLAS Edge Gateway Service ]
          |
          v
[ ATLAS Task Scheduler & Control Plane ]
```

### Critical Security Rule
**NO INBOUND PORTS ON EDGE DEVICES.**  
Edge nodes (Windows workstations, Linux edge servers, ARM64 IoT gateways) must NEVER expose incoming SSH, RDP, or HTTP ports. All traffic is established outbound from the edge node to the ATLAS Edge Gateway.

---

## 2. Authentication & Enrollment

1. **Edge Enrollment Token**: Cryptographically signed JWT issued by the tenant administrator containing:
   - `edge_id`: Unique persistent identifier of the edge node.
   - `org_id`: Owning enterprise organization.
   - `scope`: Authorized capabilities (e.g. `["browser", "cli", "desktop"]`).
   - `exp`: Token expiration timestamp.
2. **Mutual Authentication**:
   - Edge worker verifies gateway TLS certificate against pinned root CA.
   - Gateway verifies edge worker enrollment token and hardware fingerprint on handshake.
3. **Hardware Fingerprint**: SHA-256 hash of machine GUID, CPU serial, and MAC address prevents token theft and cloning.

---

## 3. Disconnection & Offline Durability

In industrial and field environments, WAN connectivity may be intermittent.

### Resilient Buffering Protocol
1. **Assignment Delivery**: Gateway delivers task assignment to worker over established WebSocket connection.
2. **Local Persistence**: Worker commits assignment immediately to local encrypted SQLite storage before execution starts.
3. **Execution Continuity**: If connection drops during task execution, the worker continues execution safely until completion or local timeout.
4. **Offline Evidence Buffering**: Screenshots, DOM snapshots, and action ledgers are accumulated in the local store.
5. **Deterministic Re-Synchronization**: Upon network restoration:
   - Worker initiates reconnection to Edge Gateway.
   - Gateway checks whether assignment lease has expired. If still valid, worker uploads full execution evidence and status.
   - If lease expired and was reassigned, worker discards side effects and reconciles state safely.

---

## 4. Remote Revocation & Fleet Security

1. **Instant Revocation**: When an administrator revokes an edge device in the Enterprise Admin Console:
   - Control plane pushes `REVOKE_EDGE_NODE` to the Edge Gateway.
   - Edge Gateway immediately terminates the active connection.
   - Worker token is blacklisted in Redis and PostgreSQL.
2. **Local Wipe**: Upon receiving a revocation signal, the edge worker daemon halts all running tasks and clears local credential caches.
