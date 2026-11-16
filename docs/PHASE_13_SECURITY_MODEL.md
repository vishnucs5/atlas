# ATLAS Phase 13 Multimodal Security Model & Threat Mitigations

---

## 1. Multimodal Threat Landscape

Introducing vision, audio, and document ingestion exposes the autonomous operating platform to adversarial attack vectors unique to multimodal systems:

| Threat Vector | Attack Mechanism | Impact | ATLAS Mitigation |
| :--- | :--- | :--- | :--- |
| **Visual Prompt Injection** | Malicious text rendered in images or webpages (e.g. white-on-white text, hidden overlays, QR codes). | Model hijacking, unauthorized action execution. | Mandatory OCR scanning, `PromptInjectionScanner`, and strict Action Firewall policy gating. |
| **Document Prompt Injection** | Invisible text layers, malicious PDF annotations, or embedded font glyph remapping. | Hijacking document summarizer or extraction workflows. | Sanitization of parsed text, heuristic injection detection, separate untrusted text tags. |
| **Decompression Bombs (Zip / Image)** | Highly compressed images or PDFs that expand to gigabytes in memory (e.g. 42.zip, 10000x10000 px monochrome PNG). | Denial of service (OOM crash) of worker pods. | Byte size limits, maximum decompression ratio check (100:1 max ratio, 50MB max file size). |
| **Audio Injection / Acoustic Attacks** | Ultrasonic or obfuscated speech commands in video/audio clips. | Execution of malicious spoken commands. | Audio consent tokens, transcript injection scanning, Action Firewall permission checks. |
| **Unauthorized Audio Recording** | Background microphone surveillance without user awareness. | Privacy violations, wiretap law breaches, compliance failure. | Cryptographically signed `AudioConsentToken` required before recording begins. |
| **Sensitive Media Data Exfiltration** | Forwarding confidential internal screenshots or financial PDFs to external cloud LLM APIs. | Data leakage, intellectual property theft. | Sensitivity classification (`INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`) routing to local GPU models. |
| **Cross-Tenant Artifact Poisoning** | Malicious tenant uploading corrupted artifact references to poll other tenants' episodic memory. | Cross-tenant data breach or memory corruption. | Tenant isolation in `MultimodalMemoryStore` and content-hash authorization in `ArtifactManager`. |

---

## 2. In-Depth Defensive Architectures

### 2.1 The Multimodal Action Firewall Barrier
No perceptual input can directly execute a system call or UI interaction. The sequence is strictly unidirectional and validated:
1. `Observation` captured by low-level driver.
2. `Visual/Audio/Document Engine` parses observation into structured tokens & detections.
3. `PromptInjectionScanner` inspects all recognized text strings. If suspicious phrases are found (e.g. `IGNORE PREVIOUS INSTRUCTIONS`, `DELETE ALL FILES`, `SYSTEM OVERRIDE`), the observation is flagged with high threat risk.
4. `Hierarchical Planner` proposes next action.
5. `ActionFirewall.evaluate(action, context)` evaluates policy rules (`ALLOW`, `REQUIRE_APPROVAL`, `DENY`).
6. Only if `ALLOW` is returned does execution proceed.

### 2.2 Local vs. Remote Inference Routing
Organizations specify privacy zones for media:
- **PUBLIC / LOW RISK**: Can be routed to high-throughput cloud providers (e.g. OpenAI GPT-4o, Google Gemini, Anthropic Claude).
- **CONFIDENTIAL / RESTRICTED**: Strictly routed to local, on-premises GPU inference nodes (e.g. vLLM with Qwen-VL or Llama-3-Vision). Cloud routing attempts for restricted media are aborted with `DataPrivacyRoutingError`.
