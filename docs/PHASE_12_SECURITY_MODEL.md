# ATLAS Phase 12 Security Model & Threat Assessment
## Kubernetes & Edge Security Architecture

---

## 1. Kubernetes Threat Model & Mitigation Matrix

| Threat ID | Threat Vector | Target Component | Impact | Mitigation Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **TH-01** | Container Escape | Worker Pod | Host OS compromise | Enforce Restricted Pod Security Standard: non-root UID 10001, `readOnlyRootFilesystem: true`, `drop: ["ALL"]`, `allowPrivilegeEscalation: false`. |
| **TH-02** | Cluster Egress Data Exfiltration | Compromised Worker | Data leak to external C2 | Kubernetes `NetworkPolicy` blocking all egress by default; explicit domain allowlisting for required APIs. |
| **TH-03** | Cross-Tenant Worker Injection | Multi-tenant cluster | Unauthorized task execution | Tenant-aware scheduling; pods run under dedicated ServiceAccounts with per-tenant namespace or node pool isolation. |
| **TH-04** | Plaintext Secret Leakage | Git / Helm Charts | Database / API key exposure | No secrets in Helm charts; integration with Kubernetes Secrets, HashiCorp Vault, or AWS Secrets Manager. |
| **TH-05** | Rogue Edge Node Spoofing | Edge Gateway | Malicious assignment fetch | Mutual TLS with hardware fingerprint binding; per-tenant enrollment token validation and immediate revocation list. |
| **TH-06** | Stale Worker Split-Brain | Distributed Scheduler | Duplicate non-idempotent action | Monotonic lease fencing tokens; database rejects state commits from stale worker epochs. |
| **TH-07** | Operator Privilege Escalation | ATLAS Operator | Full cluster takeover | Minimal RBAC ClusterRole restricted only to `atlas.io` CRDs and namespaced Deployments/Services. |

---

## 2. Pod Security Controls

Every ATLAS container deployed by Helm or the Operator enforces:
```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
  seccompProfile:
    type: RuntimeDefault
```

---

## 3. Network Policy Architecture

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: atlas-default-deny-all
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```
Dedicated NetworkPolicies explicitly allow:
- Ingress from Ingress Controller to API pods on port 8000.
- Egress from API/Supervisor to PostgreSQL (port 5432) and Redis (port 6379).
- Egress from API/Supervisor to OpenTelemetry Collector (port 4318).
- Egress from Edge Gateway to Control Plane internal ports.
