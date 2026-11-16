# ATLAS Phase 13 Risk Register & Operational Mitigations

---

## Risk Matrix

| Risk ID | Description | Severity | Probability | Mitigation Strategy | Owner |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RSK-MM-01** | Visual click drift due to dynamic CSS or DOM reflow between perception and execution. | HIGH | MEDIUM | Enforce `StaleCoordinateGuard` with 5.0s maximum age and post-action visual state diff verification. | Perception Lead |
| **RSK-MM-02** | Decompression bomb exhausts memory during image or PDF parsing. | CRITICAL | LOW | Strict header parsing, 50MB file size ceiling, and maximum 100:1 uncompressed-to-compressed ratio check. | Security Lead |
| **RSK-MM-03** | Visual prompt injection fools vision-language model into issuing destructive commands. | CRITICAL | MEDIUM | Action Firewall policy firewall intercepts all actions; OCR text scanned for adversarial keywords. | Security Lead |
| **RSK-MM-04** | Unauthorized background microphone recording causing compliance or legal violation. | CRITICAL | LOW | Cryptographic `AudioConsentToken` mandatory for opening microphone streams; missing token aborts immediately. | Compliance Lead |
| **RSK-MM-05** | Sensitive corporate documents/screenshots routed to public external LLM endpoints. | HIGH | MEDIUM | Metadata privacy tags (`RESTRICTED`); router rejects remote cloud endpoints if tags demand local GPU. | Data Governance |
| **RSK-MM-06** | GPU worker starvation or out-of-memory during heavy multimodal batch inference. | HIGH | MEDIUM | GPU capability matching via `GPUCapabilityManager` with VRAM checks and concurrency limits. | Infra Lead |
| **RSK-MM-07** | Cross-tenant memory leaks via shared episodic memory cache. | CRITICAL | LOW | Explicit `tenant_id` mandatory in all queries; strict rejection of mismatched tenant requests. | Platform Lead |
| **RSK-MM-08** | Incompatible or missing model modalities cause silent failure or hallucinated execution. | MEDIUM | HIGH | Explicit `MultimodalCapability` declaration per provider; unsupported modality fails fast with clear error. | Architecture Lead |
