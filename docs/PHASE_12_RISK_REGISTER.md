# ATLAS Phase 12 Risk Register
## Cloud-Native Infrastructure & Edge Risks

| Risk ID | Category | Description | Likelihood | Impact | Severity | Mitigation Strategy | Status |
| :---: | :--- | :--- | :---: | :---: | :---: | :--- | :---: |
| **RSK-01** | Infrastructure | Host lacks WSL/Docker daemon on local dev Windows machine | HIGH | LOW | MEDIUM | Utilize Helm CLI linting, template generation, client dry-run validation, and in-memory mock K8s API controllers for test automation. | **MITIGATED** |
| **RSK-02** | Security | Secret leakage in Helm values files committed to Git | MEDIUM | CRITICAL | HIGH | Enforce strictly parameterized Secret references in Helm charts; never commit plaintext values to Git. | **MITIGATED** |
| **RSK-03** | Operations | Pod flapping / crash looping during rolling upgrades | MEDIUM | HIGH | HIGH | Configure Readiness, Liveness, and Startup probes with adequate initial delays; PodDisruptionBudgets enforce minimum availability. | **MITIGATED** |
| **RSK-04** | Performance | Autoscaler oscillation (flapping between scale up and scale down) | HIGH | MEDIUM | MEDIUM | Implement asymmetric cooldown periods (30s scale-up cooldown, 300s scale-down cooldown) and max-step scaling bounds. | **MITIGATED** |
| **RSK-05** | Reliability | Split-brain duplicate task execution across multiple clusters | LOW | CRITICAL | HIGH | Monotonic lease fencing tokens; database rejects updates from stale worker epochs. | **MITIGATED** |
| **RSK-06** | Hardware | GPU driver version mismatch between worker and model runtime | HIGH | HIGH | HIGH | Detailed GPU capability discovery records driver version, CUDA version, compute capability, and matches explicit task requirements. | **MITIGATED** |
| **RSK-07** | Network | Intermittent edge WAN disconnection during non-idempotent action | HIGH | HIGH | HIGH | Durable local SQLite assignment buffer on edge workers with safe state reconciliation upon reconnect. | **MITIGATED** |
