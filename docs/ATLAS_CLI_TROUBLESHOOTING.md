# ATLAS CLI Troubleshooting & Diagnostics Guide

Common diagnostic scenarios, error codes, and resolution steps for ATLAS CLI.

---

## 1. Quick Diagnostics

Whenever encountering unexpected behavior, run the built-in diagnostic doctor:

```bash
atlas doctor
```

This verifies:
1. Python runtime version ($\ge 3.11$).
2. Operating system and path encoding.
3. SQLite WAL journal mode write capabilities.
4. Playwright Chromium browser binary availability.
5. Workspace `.atlas/` configuration integrity.

---

## 2. Common Scenarios & Resolutions

### A. `ActionFirewallDeniedError: Action 'terminal.exec' denied by policy`
- **Cause**: An autonomous agent attempted to run a shell command that violates active security policy or is classified as destructive.
- **Resolution**:
  - Review the proposed command in the approval prompt or logs.
  - Inspect active policies via `atlas permissions`.
  - If the command is legitimate for your project, add an authorized rule to `.atlas/config.json` or approve the request explicitly using `atlas approval grant <request_id>`.

---

### B. `OptimisticConcurrencyError: File modified concurrently`
- **Cause**: The file on disk changed after the model observed it, causing an SHA-256 pre-condition mismatch.
- **Resolution**:
  - ATLAS prevents silent overwrites.
  - Review the latest file state on disk.
  - Re-run the coding prompt; the explorer will re-index the latest contents and regenerate the patch.

---

### C. `PrivilegeBoundaryViolationError: Requested ceiling exceeds user ceiling`
- **Cause**: A workspace profile declared a privilege ceiling higher than the authenticated user's RBAC role.
- **Resolution**:
  - Switch to a profile matching your role (e.g. `python-dev` or `typescript-dev` with `STANDARD_USER` ceiling).
  - Authenticate with an administrative identity if performing platform-level changes.

---

### D. `SkillValidationError: Adversarial instruction pattern detected`
- **Cause**: A custom skill instruction matched a prompt injection heuristic (e.g. attempting to override system policy or bypass firewall).
- **Resolution**:
  - Review the skill instructions.
  - Ensure instructions state the engineering goal directly without prompt engineering meta-directives.

---

### E. SQLite Database Locks (`database is locked`)
- **Cause**: Multiple CLI instances accessing the same `.atlas/sessions.db` concurrently without WAL mode.
- **Resolution**:
  - Run `atlas doctor` to confirm WAL mode is active.
  - Check for orphan background worker processes using `atlas workers list`.
  - Terminate stale processes or wait for long-running transactions to complete.
