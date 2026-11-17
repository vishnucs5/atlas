# ATLAS Phase 16.3 Independent Audit: Enterprise Connectors & Credential Security

**Audit Target Branch:** `feat/phase-16-2-remediation`  
**Base Commit:** `88d077405dfe8e53eb9708434c594993b9ce96e0`  
**Target Module:** `packages/atlas-process/src/atlas_process/connectors.py`  
**Audit Date:** November 17, 2026  
**Auditor:** ATLAS Independent Audit Team (Phase 16.3)  
**Status:** Partially Remediated; Significant Transport & SSRF Caveats

---

## 1. Executive Summary

Phase 16.1 identified that enterprise connectors stored API secrets as plaintext strings in configuration dictionaries and relied on mock transports. Phase 16.2 introduced `SecretCredential` to mask tokens in string representations and added an HTTP-backed connector (`HttpEnterpriseConnector`) supporting retry policies and exponential backoff.

The independent audit confirmed that string redaction successfully prevents credential leakage in logs and trace dumps. However, the implementation lacks true cryptographic encryption at rest, uses synchronous blocking HTTP I/O that blocks the event loop, and introduces Server-Side Request Forgery (SSRF) vulnerabilities due to missing IP allowlisting.

---

## 2. Credential Security Assessment (Finding REM-16.1-08)

### 2.1 String Redaction & Masking
`SecretCredential` wraps sensitive strings:
```python
class SecretCredential:
    def __init__(self, value: str) -> None:
        self._value = value

    def __repr__(self) -> str:
        return "**********"

    def __str__(self) -> str:
        return "**********"
```
- **Verification:**
  - Printing instances or converting them to strings (`f"{cred}"`, `repr(cred)`) prints `**********`.
  - Exception traces and structured logs do not expose the underlying key.
  - Access to raw credentials requires calling `.get_secret_value()`.

### 2.2 Lack of At-Rest Cryptographic Protection
- `SecretCredential` stores the secret as a standard Python heap string (`self._value`).
- In `PostgresProcessStorage.save_connector_definition()`, connector configuration dictionaries are serialized to JSON. If credentials are included in the configuration payload, they are stored in plaintext in the database `process_connector_definitions` table unless an external database encryption mechanism (TDE) is configured.
- No client-side encryption (e.g., Fernet, envelope encryption via AWS KMS/GCP KMS/HashiCorp Vault) is implemented.

---

## 3. Transport & Concurrency Defect (NEW-16.3-06)

### 3.1 Synchronous Blocking in Async Runtime
In `packages/atlas-process/src/atlas_process/connectors.py:165-182`:
```python
class HttpEnterpriseConnector(EnterpriseConnector):
    def invoke(self, action: str, parameters: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = client.request(...)
                    ...
                except Exception:
                    if attempt < self.max_retries - 1:
                        time.sleep(self.backoff_factor * (2**attempt))
```

### 3.2 Concurrency Impact
1. `HttpEnterpriseConnector.invoke` is a synchronous function utilizing `httpx.Client` and `time.sleep()`.
2. When called within an `asyncio` event loop (such as inside the ATLAS engine or FastAPI request worker), `time.sleep()` **halts the entire operating thread and freezes all concurrent asyncio tasks**.
3. Under network degradation (e.g. a 5-second timeout with 3 retries and exponential backoff), a single worker thread will block for over 20 seconds, starving health checks, heartbeats, and peer process execution.

---

## 4. Server-Side Request Forgery (SSRF) Threat (NEW-16.3-07)

### 4.1 Threat Model
`HttpEnterpriseConnector` accepts an arbitrary `base_url` parameter from workflow definition metadata or connector configurations.

### 4.2 Missing Guardrails
The connector performs no IP or hostname validation:
- **Cloud Metadata Endpoints:** Targets such as `http://169.254.169.254/latest/meta-data/` (AWS/GCP/Azure) are reachable if workflows are configured or modified by unauthorized tenants.
- **Internal RFC-1918 Networks:** Requests to `http://10.0.0.0/8`, `http://172.16.0.0/12`, `http://192.168.0.0/16` are not blocked.
- **Localhost / Loopback:** Requests to `http://127.0.0.1:5432` or `http://localhost:8000` are permitted.
- **DNS Rebinding:** No IP pinning or DNS resolution validation is performed prior to connection.

---

## 5. Enterprise Protocol Authenticity

The SAP and Salesforce connectors provided in `packages/atlas-process/src/atlas_process/connectors.py` are lightweight subclass wrappers configuring headers and URLs for `HttpEnterpriseConnector`.
- They do not implement authentic SAP OData v2/v4, NetWeaver RFC, or SAP IDoc protocols.
- They do not implement Salesforce OAuth JWT Bearer Flow, Bulk API 2.0, or Pub/Sub API.
- They are generic HTTP RPC adapters requiring pre-configured REST gateways on the enterprise target side.

---

## 6. Audit Verdict

| Dimension | Finding | Assessment |
| :--- | :--- | :--- |
| **Credential Masking** | REM-16.1-08 | **CLOSED** (Log redaction verified) |
| **At-Rest Encryption** | REM-16.1-08 | **OPEN** (Requires KMS / vault integration) |
| **Event Loop Blocking** | NEW-16.3-06 | **HIGH DEFECT** (Sync `httpx` + `time.sleep`) |
| **SSRF Vulnerability** | NEW-16.3-07 | **HIGH DEFECT** (Unrestricted target URL reach) |
| **Enterprise Protocols** | REM-16.1-09 | **GENERIC ONLY** (Standard REST proxy pattern) |

**Overall Status:** Suitable only for controlled internal testing with trusted workflow definitions. Unsafe for multi-tenant self-service or unconstrained external network invocation.
