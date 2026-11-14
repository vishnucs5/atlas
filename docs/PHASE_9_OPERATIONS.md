# ATLAS Phase 9 Operations Guide: Distributed Deployment & Fleet Administration

**Version:** 1.0.0  
**Target:** Site Reliability Engineers, System Administrators, and DevOps

---

## 1. Deployment Topologies

ATLAS Distributed Execution Network supports multiple deployment topologies tailored to different operational requirements:

### Topology A: Local Development & Multi-Process Simulation
- **Control Plane**: Single FastAPI server backed by SQLite (WAL mode).
- **Workers**: Multiple `WorkerAgent` daemons running as separate OS processes on localhost, exercising multi-process concurrency, fencing tokens, and network reconnection over loopback.

### Topology B: Production Enterprise Cluster (Recommended)
- **Control Plane**: Multi-instance FastAPI behind a TLS reverse proxy (Nginx / Cloudflare), backed by High-Availability PostgreSQL 16+.
- **Workers**:
  - **Windows 11 Physical Machines**: Dedicated interactive automation hosts running the Worker Agent in an active unlocked desktop session.
  - **Linux VMs / Bare-Metal**: High-throughput servers running the Worker Agent via `systemd`.
  - **Cloud Kubernetes Pods**: Auto-scaling worker pods executing ephemeral scraping and data analysis subtasks.

---

## 2. Worker Agent Installation & Setup

### 2.1 Windows 11 Interactive Desktop Worker
> [!IMPORTANT]
> **Windows Session 0 Invariant**: Windows Services execute in Session 0, which has no interactive GUI desktop surface. Do NOT run the worker agent as a native Windows Service if it executes PyAutoGUI or interactive desktop tasks. Run it within an authenticated user session (e.g. via Windows Task Scheduler "Run only when user is logged on" or Startup folder).

1. **Install Python & ATLAS Package**:
   ```powershell
   git clone https://github.com/atlas/atlas.git
   cd atlas
   uv sync --all-packages
   ```
2. **Obtain Enrollment Token from Control Plane**:
   ```powershell
   $token = (Invoke-RestMethod -Uri "http://control-plane:8000/api/v1/distributed/tokens" -Method Post -Headers @{ Authorization = "Bearer admin-key" } -Body '{"tenant_id": "default", "expires_in_hours": 24}' -ContentType "application/json").token
   ```
3. **Enroll & Start Worker Agent**:
   ```powershell
   uv run atlas-worker enroll --control-plane http://control-plane:8000 --token $token --capabilities browser,desktop,windows_uia
   uv run atlas-worker run --control-plane http://control-plane:8000
   ```

### 2.2 Linux Headless Worker Daemon (`systemd`)
1. Create systemd unit `/etc/systemd/system/atlas-worker.service`:
   ```ini
   [Unit]
   Description=ATLAS Distributed Worker Agent
   After=network.target

   [Service]
   Type=simple
   User=atlas
   WorkingDirectory=/opt/atlas
   ExecStart=/opt/atlas/.venv/bin/python -m atlas_distributed.worker --control-plane http://control-plane:8000
   Restart=always
   RestartSec=5
   Environment=ATLAS_WORKER_CONFIG=/etc/atlas/worker.json

   [Install]
   WantedBy=multi-user.target
   ```
2. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now atlas-worker
   ```

---

## 3. Fleet Administration & Security Runbooks

### 3.1 Provisioning a New Worker
Administrators generate scoped enrollment tokens via CLI or API:
```bash
curl -X POST http://control-plane:8000/api/v1/distributed/tokens \
  -H "Authorization: Bearer admin-key" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "org_engineering", "max_uses": 1, "expires_in_hours": 2}'
```

### 3.2 Immediate Worker Revocation
If a worker machine is compromised, revoked immediately via API:
```bash
curl -X POST http://control-plane:8000/api/v1/distributed/workers/worker_win11_03/revoke \
  -H "Authorization: Bearer admin-key" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Host security compromise suspected"}'
```
- Control plane marks worker `REVOKED`.
- Active leases are cancelled.
- Fencing tokens reject any further execution commits from this worker.

### 3.3 Unknown External Side-Effect Reconciliation Runbook
When a worker crashes during a non-idempotent action:
1. Control Plane marks action status as `UNKNOWN` in `ActionLedger`.
2. Recovery Manager suspends automatic reassignment and sets task to `PAUSED`.
3. Operator reviews the external state (e.g. checks whether external transaction was posted).
4. Operator resolves via Dashboard or API:
   - If action succeeded externally: `POST /api/v1/distributed/reconcile { "task_id": "...", "status": "ALREADY_COMPLETED" }`
   - If action failed externally: `POST /api/v1/distributed/reconcile { "task_id": "...", "status": "SAFE_TO_RETRY" }`
