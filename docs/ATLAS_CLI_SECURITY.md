# ATLAS CLI Security Certification & Threat Defense Architecture

## 1. Threat Model & Security Posture

Autonomous coding agents pose unique security challenges: they interpret unstructured natural language, parse untrusted repository code, interact with external tools, and execute shell commands. ATLAS CLI addresses these threats through a defense-in-depth security model:

```
┌────────────────────────────────────────────────────────┐
│                   Untrusted Boundary                   │
│         (Prompts, Repository Files, MCP Tools)         │
└───────────────────────────┬────────────────────────────┘
                            │ Sanitization & Tagging
                            ▼
┌────────────────────────────────────────────────────────┐
│                    Action Firewall                     │
│         (Deterministic Pre-Execution Policy)           │
└───────────────────────────┬────────────────────────────┘
                            │ Authorization
                            ▼
┌────────────────────────────────────────────────────────┐
│                   Human-in-the-Loop                    │
│            (Cryptographic Parameter Binding)           │
└───────────────────────────┬────────────────────────────┘
                            │ Approved
                            ▼
┌────────────────────────────────────────────────────────┐
│              Hermetic Execution Drivers                │
│             (shell=False, Bounded Sandbox)             │
└────────────────────────────────────────────────────────┘
```

---

## 2. Security Dimensions & Defense Mechanisms

### A. Action Firewall Authority
- All executable actions (`file.write`, `terminal.exec`, `mcp.<tool>`) must pass policy evaluation before execution.
- Rules map exact action types or hierarchical prefixes to decisions (`ALLOW`, `DENY`, `REQUIRE_APPROVAL`).
- Tool docstrings, model instructions, or system prompts **cannot grant permissions**.

### B. Filesystem Security & Path Traversal Guards
- All file reads and writes are restricted to the validated workspace root via `resolve().is_relative_to(repo_root)`.
- Rejects directory traversal attempts (`../../etc/passwd`).
- Blocks Windows UNC paths (`\\server\share`) and reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`).
- Symlinks pointing outside the repository tree are rejected.

### C. Terminal Security & Shell Injection Defense
- Subprocesses execute with `shell=False` exclusively using tokenized argument vectors.
- Direct command-chaining characters (`;`, `&&`, `||`, `|`, `` ` ``, `$()`) are blocked.
- Blacklisted destructive commands (`rm -rf /`, `mkfs`, `dd if=/dev/zero`, fork bombs) trigger hard aborts.
- Environment variables and CLI output are dynamically scrubbed by `SECRET_REGEX` to prevent secret leaks.

### D. Adversarial Prompt Injection Neutralization
- Untrusted repository content and external tool outputs are tagged `is_untrusted: True`.
- Skill instructions are pre-screened against prompt injection regex patterns (`ignore previous instructions`, `override system policy`).
- Untrusted content is wrapped in delimited containment blocks that models are instructed not to interpret as system directives.

### E. Supply-Chain & Dependency Security
- Live vulnerability scanning via `pip-audit` integrated into CI gates (blocks on $\ge$ MODERATE).
- CycloneDX v1.5 Software Bill of Materials (SBOM) generated with exact package hashes.
- Plugin packages validated with SHA-256 integrity checksums and publisher trust verification.
