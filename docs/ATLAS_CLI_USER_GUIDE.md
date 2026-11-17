# ATLAS CLI User Guide

## 1. Architecture & Execution Loop

ATLAS CLI operates on an invariant-enforced execution loop designed to guarantee that models propose changes while deterministic systems authorize and verify execution:

```
  ┌────────────────────────────────────────────────────────┐
  │                 ATLAS Execution Loop                   │
  │                                                        │
  │    [ OBSERVE ] ──> [ PLAN ] ──> [ FIREWALL EVAL ]      │
  │          ▲                              │              │
  │          │                              ▼              │
  │    [ VERIFY ] <── [ EXECUTE ] <── [ APPROVAL GATE ]    │
  │          │                                             │
  │          ▼                                             │
  │    [ CHECKPOINT / COMPLETE ]                           │
  └────────────────────────────────────────────────────────┘
```

1. **Observe**: Gathers repository context, symbol references, and active diffs without token-budget blowup.
2. **Plan**: Formulates an explicit step-by-step DAG of operations with classified risk levels (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
3. **Firewall Evaluation**: Every proposed file modification, shell command, or MCP invocation is routed through `ActionFirewall`.
4. **Approval Gate**: Operations marked `CRITICAL` or exceeding the workspace privilege ceiling suspend execution into a `WAITING_APPROVAL` state.
5. **Execute**: Atomic file operations and subprocesses execute via safe argument vectors (`shell=False`).
6. **Verify**: Post-action verification ensures deterministic evidence (e.g. tests passing, exit code 0) before reporting success.
7. **Checkpoint**: State changes are saved into append-only SQLite WAL storage.

---

## 2. Managing Workspace Profiles

ATLAS automatically detects the appropriate development environment profile based on project files:

```bash
# List all built-in profiles
atlas profiles list
```

| Profile | Target Stack | Test Command | Privilege Ceiling |
| :--- | :--- | :--- | :--- |
| `python-dev` | Python (pytest, ruff) | `pytest` | `STANDARD_USER` |
| `typescript-dev` | TypeScript / JS (npm, prettier) | `npm test` | `STANDARD_USER` |
| `java-backend` | Java / Maven (JUnit, Spotless) | `mvn test` | `STANDARD_USER` |
| `machine-learning` | Python (PyTorch, Jupyter, high token budget) | `pytest` | `STANDARD_USER` |
| `infrastructure` | Docker, Terraform, Kubernetes | `docker build .` | `STANDARD_USER` |
| `security-review` | Multi-language audit, secret scanning | `pip-audit` | `STANDARD_USER` |

To switch profiles:
```bash
atlas config set profile typescript-dev
```

---

## 3. Reviewing Diffs & Independent Code Review

Before committing changes synthesized by ATLAS, run an adversarial code review:

```bash
# Perform independent adversarial audit of staged modifications
atlas review --diff
```

The `IndependentCodeReviewer` inspects:
- Correctness and adherence to requirements.
- Absence of hardcoded credentials or API tokens.
- Absence of shell injection or path traversal vulnerabilities.
- Absence of subtle logic bugs or unhandled edge cases.

---

## 4. Session History and Recovery

Every conversation turn and file change is tracked across sessions:

```bash
# List past sessions
atlas sessions list

# Resume an interrupted session
atlas sessions resume sess_a1b2c3d4e5f6

# Export session audit log to JSON
atlas sessions export sess_a1b2c3d4e5f6 --output audit_log.json
```
