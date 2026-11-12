# Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ATLAS Phase 1 (Foundation & Core Lifecycle): Monorepo workspace, AGENTS.md constitution, architecture docs, ADRs, shared Pydantic v2 contracts, explicit Task State Machine, event-sourced SQLite storage, PostgreSQL interface, context-aware structured logging, FastAPI health service, developer CLI (`atlas doctor` / `atlas init` / `atlas task`), and CI workflow to satisfy all 14 Phase 1 acceptance criteria.

**Architecture:** Monorepo using `uv` workspaces with `atlas-core` as a zero-dependency domain root. Task execution events are sequenced and stored in an immutable SQLite event log alongside a materialized task view. Actions pass through the `atlas-policy` Action Firewall before execution. Telemetry uses JSON structured logging with credential masking. `apps/api` exposes FastAPI endpoints and `apps/cli` provides CLI commands.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, SQLite (standard library sqlite3 with WAL mode), Click / Argparse, Pytest, Ruff, uv, GitHub Actions.

**Spec:** [docs/superpowers/specs/2026-11-12-phase-1-foundation-design.md](file:///c:/Users/pc/Documents/antigravity/happy-meitner/docs/superpowers/specs/2026-11-12-phase-1-foundation-design.md)

## Global Constraints

- `atlas-core` must have ZERO dependencies on operating system libraries, model providers, or database drivers.
- Every action must pass through the policy engine / action firewall.
- Every task mutation must emit an immutable, sequence-numbered `ExecutionEvent`.
- The task state machine must reject invalid transitions by raising `InvalidStateTransitionError`.
- No placeholder code in production paths.
- No secrets (API keys, passwords, tokens) logged in plain text.
- Target Windows 11 first, with cross-platform interfaces.

---

### Task 1: Monorepo Workspace, Governance & Documentation Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `ruff.toml`
- Create: `.gitignore`
- Create: `AGENTS.md`
- Create: `README.md`
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/DECISIONS.md`
- Create: `docs/IMPLEMENTATION_PLAN.md`
- Create: `docs/PROJECT_STATUS.md`
- Create: `docs/TEST_RESULTS.md`
- Create: `docs/KNOWN_ISSUES.md`
- Create: `docs/CHANGELOG.md`
- Create: `docs/adr/0001-monorepo-and-runtime-ownership.md`
- Create: `docs/adr/0002-event-sourced-task-persistence.md`
- Create: `docs/adr/0003-action-firewall-policy-separation.md`

**Interfaces:**
- Produces: Monorepo workspace configuration resolving packages and apps, project constitution, and continuity documentation.

- [ ] **Step 1: Write root workspace configuration, ruff, and gitignore**

Create `pyproject.toml`:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "atlas-monorepo"
version = "0.1.0"
description = "ATLAS - Autonomous Task & Lifecycle Automation System"
readme = "README.md"
requires-python = ">=3.11"
dependencies = []

[tool.uv.workspace]
members = [
    "packages/atlas-core",
    "packages/atlas-storage",
    "packages/atlas-policy",
    "packages/atlas-observability",
    "apps/api",
    "apps/cli",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = [
    "packages/atlas-core/src",
    "packages/atlas-storage/src",
    "packages/atlas-policy/src",
    "packages/atlas-observability/src",
    "apps/api/src",
    "apps/cli/src",
]
asyncio_mode = "auto"
```

Create `ruff.toml`:
```toml
line-length = 100
target-version = "py311"

[lint]
select = ["E", "F", "W", "I", "UP", "B", "C4"]
ignore = ["E501"]
```

Create `.gitignore`:
```
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.ruff_cache/
*.egg-info/
dist/
build/
.venv/
*.db
*.db-journal
*.db-wal
.atlas/
```

- [ ] **Step 2: Create root AGENTS.md constitution and README.md**

Create `AGENTS.md`:
```markdown
# ATLAS Engineering Constitution

Mandatory rules for every contributor, subagent, and model operating in this repository:

1. **Architecture Ownership**: Core owns orchestration, lifecycle, and tool contracts. Low-level drivers implement interfaces; they never own planning or planning state.
2. **Action Firewall**: The model makes decisions; ATLAS controls execution. No model adapter or execution worker may execute an action without authorization.
3. **Zero-Dependency Core**: `packages/atlas-core` must NEVER import external drivers, OS-specific APIs, or database engines.
4. **No Placeholders**: Never write dummy or placeholder implementations in production code paths.
5. **No Swallowing Exceptions**: Errors must be structured, logged with context, and handled via recovery or failure transitions.
6. **No Secret Leaks**: Credentials, keys, and tokens must never appear in logs, prompts, or screenshots.
7. **Verification Invariant**: An action is never reported as successful without deterministic post-condition verification.
8. **Durable Continuity**: Record all progress and blockers in `docs/PROJECT_STATUS.md` and `docs/IMPLEMENTATION_PLAN.md`.
```

- [ ] **Step 3: Create architecture documentation and ADR records**

Create `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/PROJECT_STATUS.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/TEST_RESULTS.md`, `docs/KNOWN_ISSUES.md`, `docs/CHANGELOG.md`, and ADRs:
- `docs/adr/0001-monorepo-and-runtime-ownership.md` (Core runtime ownership vs external frameworks)
- `docs/adr/0002-event-sourced-task-persistence.md` (Event sourcing with SQLite dev / PostgreSQL prod)
- `docs/adr/0003-action-firewall-policy-separation.md` (Action Firewall & policy engine separation)

- [ ] **Step 4: Verify workspace and documentation files**

Run: `git status`
Expected: Files tracked and unstaged.

- [ ] **Step 5: Commit scaffolding**

```bash
git add pyproject.toml ruff.toml .gitignore AGENTS.md README.md docs/
git commit -m "chore: scaffold monorepo workspace, governance, and architecture docs"
```

---

### Task 2: Core Data Contracts (`packages/atlas-core`)

**Files:**
- Create: `packages/atlas-core/pyproject.toml`
- Create: `packages/atlas-core/src/atlas_core/__init__.py`
- Create: `packages/atlas-core/src/atlas_core/contracts/__init__.py`
- Create: `packages/atlas-core/src/atlas_core/contracts/task.py`
- Create: `packages/atlas-core/src/atlas_core/contracts/session.py`
- Create: `packages/atlas-core/src/atlas_core/contracts/action.py`
- Create: `packages/atlas-core/src/atlas_core/contracts/observation.py`
- Create: `packages/atlas-core/src/atlas_core/contracts/event.py`
- Create: `packages/atlas-core/src/atlas_core/contracts/policy.py`
- Create: `packages/atlas-core/src/atlas_core/contracts/checkpoint.py`
- Create: `packages/atlas-core/src/atlas_core/contracts/model.py`
- Test: `tests/unit/test_contracts.py`

**Interfaces:**
- Produces: Strongly typed, versioned Pydantic v2 schemas:
  - `Task`, `TaskRequest`, `TaskStatus`, `TaskPriority`
  - `ComputerAction`, `ActionTarget`, `ActionResult`, `ExpectedState`
  - `Observation`, `ExecutionEvent`, `EventType`
  - `PolicyDecision`, `PolicyDecisionType`, `RiskLevel`, `ApprovalRequest`
  - `Checkpoint`, `ModelRequest`, `ModelResponse`, `ModelCapabilities`

- [ ] **Step 1: Write failing test for core contracts**

Create `tests/unit/test_contracts.py`:
```python
from datetime import datetime, timezone
import pytest
from atlas_core.contracts.task import Task, TaskRequest, TaskStatus, TaskPriority
from atlas_core.contracts.action import ComputerAction, ActionTarget, ActionResult, ExpectedState
from atlas_core.contracts.event import ExecutionEvent, EventType
from atlas_core.contracts.policy import PolicyDecision, PolicyDecisionType, RiskLevel
from atlas_core.contracts.observation import Observation


def test_task_contract_serialization():
    req = TaskRequest(objective="Research cloud providers", priority=TaskPriority.HIGH)
    assert req.objective == "Research cloud providers"
    assert req.priority == TaskPriority.HIGH

    now = datetime.now(timezone.utc)
    task = Task(
        task_id="task_123",
        objective=req.objective,
        status=TaskStatus.CREATED,
        priority=req.priority,
        created_at=now,
        updated_at=now,
    )
    json_data = task.model_dump_json()
    deserialized = Task.model_validate_json(json_data)
    assert deserialized.task_id == "task_123"
    assert deserialized.status == TaskStatus.CREATED


def test_computer_action_contract():
    action = ComputerAction(
        action_id="act_001",
        task_id="task_123",
        session_id="sess_456",
        action_type="browser.click",
        target=ActionTarget(
            strategy="accessible_role", parameters={"role": "button", "name": "Search"}
        ),
        expected_state=ExpectedState(condition="element_visible", target="Search results"),
        idempotency_key="task_123_act_001",
    )
    assert action.action_type == "browser.click"
    assert action.schema_version == "1.0"
    assert action.target.parameters["role"] == "button"


def test_execution_event_contract():
    now = datetime.now(timezone.utc)
    event = ExecutionEvent(
        event_id="evt_001",
        task_id="task_123",
        sequence=1,
        event_type=EventType.TASK_CREATED,
        timestamp=now,
        payload={"objective": "Test"},
        correlation_id="corr_999",
    )
    assert event.sequence == 1
    assert event.event_type == EventType.TASK_CREATED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_contracts.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'atlas_core'`

- [ ] **Step 3: Implement core contracts in packages/atlas-core**

Create `packages/atlas-core/pyproject.toml`:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "atlas-core"
version = "0.1.0"
dependencies = [
    "pydantic>=2.7.0",
]
```

Implement `task.py`, `action.py`, `observation.py`, `event.py`, `policy.py`, `session.py`, `checkpoint.py`, `model.py` in `packages/atlas-core/src/atlas_core/contracts/`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_contracts.py`
Expected: PASS

- [ ] **Step 5: Commit core contracts**

```bash
git add packages/atlas-core tests/unit/test_contracts.py
git commit -m "feat(core): implement core Pydantic v2 data contracts"
```

---

### Task 3: Task State Machine & Lifecycle (`packages/atlas-core/lifecycle`)

**Files:**
- Create: `packages/atlas-core/src/atlas_core/lifecycle/exceptions.py`
- Create: `packages/atlas-core/src/atlas_core/lifecycle/state_machine.py`
- Create: `packages/atlas-core/src/atlas_core/lifecycle/__init__.py`
- Create: `packages/atlas-core/src/atlas_core/runtime/interface.py`
- Create: `packages/atlas-core/src/atlas_core/runtime/__init__.py`
- Test: `tests/unit/test_state_machine.py`

**Interfaces:**
- Consumes: `Task`, `TaskStatus`, `ExecutionEvent`, `EventType`
- Produces: `TaskStateMachine`, `InvalidStateTransitionError`, `AtlasRuntime` protocol.

- [ ] **Step 1: Write failing tests for TaskStateMachine**

Create `tests/unit/test_state_machine.py`:
```python
import pytest
from atlas_core.contracts.task import TaskStatus
from atlas_core.lifecycle.state_machine import TaskStateMachine
from atlas_core.lifecycle.exceptions import InvalidStateTransitionError


def test_valid_lifecycle_transitions():
    sm = TaskStateMachine()
    assert sm.transition(TaskStatus.CREATED, TaskStatus.QUEUED) == TaskStatus.QUEUED
    assert sm.transition(TaskStatus.QUEUED, TaskStatus.PLANNING) == TaskStatus.PLANNING
    assert sm.transition(TaskStatus.PLANNING, TaskStatus.READY) == TaskStatus.READY
    assert sm.transition(TaskStatus.READY, TaskStatus.RUNNING) == TaskStatus.RUNNING
    assert (
        sm.transition(TaskStatus.RUNNING, TaskStatus.WAITING_APPROVAL)
        == TaskStatus.WAITING_APPROVAL
    )
    assert sm.transition(TaskStatus.WAITING_APPROVAL, TaskStatus.RUNNING) == TaskStatus.RUNNING
    assert sm.transition(TaskStatus.RUNNING, TaskStatus.VERIFYING) == TaskStatus.VERIFYING
    assert sm.transition(TaskStatus.VERIFYING, TaskStatus.COMPLETED) == TaskStatus.COMPLETED


def test_invalid_lifecycle_transition_raises():
    sm = TaskStateMachine()
    with pytest.raises(InvalidStateTransitionError):
        sm.transition(TaskStatus.CREATED, TaskStatus.COMPLETED)


def test_terminal_state_cannot_transition():
    sm = TaskStateMachine()
    with pytest.raises(InvalidStateTransitionError):
        sm.transition(TaskStatus.COMPLETED, TaskStatus.RUNNING)
    with pytest.raises(InvalidStateTransitionError):
        sm.transition(TaskStatus.FAILED, TaskStatus.QUEUED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_state_machine.py`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement TaskStateMachine & AtlasRuntime protocol**

Implement:
- `packages/atlas-core/src/atlas_core/lifecycle/exceptions.py` with `InvalidStateTransitionError(Exception)`.
- `packages/atlas-core/src/atlas_core/lifecycle/state_machine.py` with strict transition dictionary and validation methods.
- `packages/atlas-core/src/atlas_core/runtime/interface.py` with `AtlasRuntime(Protocol)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_state_machine.py`
Expected: PASS

- [ ] **Step 5: Commit state machine**

```bash
git add packages/atlas-core tests/unit/test_state_machine.py
git commit -m "feat(core): implement explicit TaskStateMachine and runtime protocols"
```

---

### Task 4: Action Firewall & Policy Engine (`packages/atlas-policy`)

**Files:**
- Create: `packages/atlas-policy/pyproject.toml`
- Create: `packages/atlas-policy/src/atlas_policy/__init__.py`
- Create: `packages/atlas-policy/src/atlas_policy/firewall.py`
- Test: `tests/unit/test_policy_firewall.py`

**Interfaces:**
- Consumes: `ComputerAction`, `PolicyDecision`, `PolicyDecisionType`, `RiskLevel`
- Produces: `ActionFirewall`, `PolicyRule`

- [ ] **Step 1: Write failing test for ActionFirewall**

Create `tests/unit/test_policy_firewall.py`:
```python
import pytest
from atlas_core.contracts.action import ComputerAction, ActionTarget
from atlas_core.contracts.policy import PolicyDecisionType, RiskLevel
from atlas_policy.firewall import ActionFirewall


def test_firewall_allows_low_risk_action():
    firewall = ActionFirewall()
    action = ComputerAction(
        action_id="act_1",
        task_id="t1",
        session_id="s1",
        action_type="browser.scroll",
        idempotency_key="k1",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.risk_level == RiskLevel.LOW


def test_firewall_requires_approval_for_destructive_action():
    firewall = ActionFirewall()
    action = ComputerAction(
        action_id="act_2",
        task_id="t1",
        session_id="s1",
        action_type="terminal.execute",
        parameters={"command": "rm -rf /"},
        idempotency_key="k2",
    )
    decision = firewall.evaluate(action)
    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.risk_level == RiskLevel.CRITICAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_policy_firewall.py`
Expected: FAIL

- [ ] **Step 3: Implement ActionFirewall**

Create `packages/atlas-policy/pyproject.toml` and implement `ActionFirewall` in `src/atlas_policy/firewall.py` with configurable rule evaluation, action prefix matching, and risk classification.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_policy_firewall.py`
Expected: PASS

- [ ] **Step 5: Commit policy firewall**

```bash
git add packages/atlas-policy tests/unit/test_policy_firewall.py
git commit -m "feat(policy): implement ActionFirewall and risk-based action evaluation"
```

---

### Task 5: Context-Bound Structured Logging (`packages/atlas-observability`)

**Files:**
- Create: `packages/atlas-observability/pyproject.toml`
- Create: `packages/atlas-observability/src/atlas_observability/__init__.py`
- Create: `packages/atlas-observability/src/atlas_observability/logging.py`
- Test: `tests/unit/test_observability.py`

**Interfaces:**
- Produces: `get_logger(name: str) -> StructuredLogger`, `bind_context(**kwargs)`, `mask_secrets(text: str) -> str`.

- [ ] **Step 1: Write failing test for structured logger and secret masking**

Create `tests/unit/test_observability.py`:
```python
import io
import json
import logging
from atlas_observability.logging import get_logger, mask_secrets, bind_context


def test_mask_secrets():
    raw = "My API key is sk-proj-1234567890abcdef12345 and password=supersecret"
    masked = mask_secrets(raw)
    assert "sk-proj-1234567890abcdef12345" not in masked
    assert "supersecret" not in masked


def test_structured_json_logging():
    stream = io.StringIO()
    logger = get_logger("atlas.test", stream=stream)
    bind_context(task_id="task_999", correlation_id="corr_888")
    logger.info("Task execution step started", action="browser.click")
    output = stream.getvalue()
    record = json.loads(output)
    assert record["message"] == "Task execution step started"
    assert record["task_id"] == "task_999"
    assert record["correlation_id"] == "corr_888"
    assert record["action"] == "browser.click"
    assert "timestamp" in record
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_observability.py`
Expected: FAIL

- [ ] **Step 3: Implement structured logger with regex masking and contextual vars**

Implement `packages/atlas-observability/src/atlas_observability/logging.py` using `contextvars` and JSON formatting.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_observability.py`
Expected: PASS

- [ ] **Step 5: Commit observability package**

```bash
git add packages/atlas-observability tests/unit/test_observability.py
git commit -m "feat(observability): implement context-bound structured JSON logger with secret redaction"
```

---

### Task 6: Event-Sourced Storage (SQLite & PostgreSQL Interface) (`packages/atlas-storage`)

**Files:**
- Create: `packages/atlas-storage/pyproject.toml`
- Create: `packages/atlas-storage/src/atlas_storage/__init__.py`
- Create: `packages/atlas-storage/src/atlas_storage/interfaces.py`
- Create: `packages/atlas-storage/src/atlas_storage/sqlite.py`
- Create: `packages/atlas-storage/src/atlas_storage/postgres.py`
- Test: `tests/unit/test_sqlite_storage.py`

**Interfaces:**
- Consumes: `Task`, `ExecutionEvent`, `TaskStatus`
- Produces: `TaskStoreProtocol`, `EventStoreProtocol`, `SQLiteTaskStore`, `PostgresTaskStoreInterface`.

- [ ] **Step 1: Write failing test for SQLite event sourcing and materialized task view**

Create `tests/unit/test_sqlite_storage.py`:
```python
from datetime import datetime, timezone
import pytest
from atlas_core.contracts.task import Task, TaskStatus, TaskPriority
from atlas_core.contracts.event import ExecutionEvent, EventType
from atlas_storage.sqlite import SQLiteStorage


def test_sqlite_task_and_event_lifecycle(tmp_path):
    db_file = tmp_path / "test_atlas.db"
    store = SQLiteStorage(str(db_file))
    store.initialize()

    now = datetime.now(timezone.utc)
    task = Task(
        task_id="t_001",
        objective="Run benchmark",
        status=TaskStatus.CREATED,
        priority=TaskPriority.NORMAL,
        created_at=now,
        updated_at=now,
    )
    store.save_task(task)

    fetched = store.get_task("t_001")
    assert fetched is not None
    assert fetched.task_id == "t_001"
    assert fetched.status == TaskStatus.CREATED

    evt = ExecutionEvent(
        event_id="e_001",
        task_id="t_001",
        sequence=1,
        event_type=EventType.TASK_CREATED,
        timestamp=now,
        payload={"objective": task.objective},
        correlation_id="c_001",
    )
    store.append_event(evt)
    events = store.get_events("t_001")
    assert len(events) == 1
    assert events[0].event_id == "e_001"
    assert events[0].sequence == 1

    # Transition status
    store.update_task_status("t_001", TaskStatus.RUNNING)
    updated = store.get_task("t_001")
    assert updated.status == TaskStatus.RUNNING
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_sqlite_storage.py`
Expected: FAIL

- [ ] **Step 3: Implement SQLiteStorage and PostgreSQL interface specification**

Create `packages/atlas-storage/src/atlas_storage/`:
- `interfaces.py`: `TaskStoreProtocol`, `EventStoreProtocol`
- `sqlite.py`: `SQLiteStorage` with WAL mode, schema DDL, and transactional queries
- `postgres.py`: `PostgresStorageSpec` defining connection pool configuration and table schemas

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_sqlite_storage.py`
Expected: PASS

- [ ] **Step 5: Commit storage package**

```bash
git add packages/atlas-storage tests/unit/test_sqlite_storage.py
git commit -m "feat(storage): implement SQLite event-sourced storage and PostgreSQL interface"
```

---

### Task 7: FastAPI Health & Status Service (`apps/api`)

**Files:**
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/src/atlas_api/__init__.py`
- Create: `apps/api/src/atlas_api/main.py`
- Create: `apps/api/src/atlas_api/routes/__init__.py`
- Create: `apps/api/src/atlas_api/routes/health.py`
- Test: `tests/unit/test_api_health.py`

**Interfaces:**
- Produces: FastAPI application with endpoints:
  - `GET /health` -> `{"status": "healthy", "version": "0.1.0", "timestamp": ...}`
  - `GET /v1/status` -> Detailed system and storage status.

- [ ] **Step 1: Write failing test for FastAPI health routes**

Create `tests/unit/test_api_health.py`:
```python
from fastapi.testclient import TestClient
from atlas_api.main import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"
    assert "timestamp" in data


def test_v1_status_endpoint():
    client = TestClient(app)
    response = client.get("/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert "components" in data
    assert data["components"]["api"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_api_health.py`
Expected: FAIL

- [ ] **Step 3: Implement FastAPI application and health routes**

Implement `apps/api/pyproject.toml` and `src/atlas_api/main.py` and `routes/health.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_api_health.py`
Expected: PASS

- [ ] **Step 5: Commit API package**

```bash
git add apps/api tests/unit/test_api_health.py
git commit -m "feat(api): implement FastAPI application with health and component status endpoints"
```

---

### Task 8: Developer CLI (`apps/cli`)

**Files:**
- Create: `apps/cli/pyproject.toml`
- Create: `apps/cli/src/atlas_cli/__init__.py`
- Create: `apps/cli/src/atlas_cli/main.py`
- Create: `apps/cli/src/atlas_cli/commands/__init__.py`
- Create: `apps/cli/src/atlas_cli/commands/doctor.py`
- Create: `apps/cli/src/atlas_cli/commands/init.py`
- Create: `apps/cli/src/atlas_cli/commands/task.py`
- Test: `tests/integration/test_cli.py`

**Interfaces:**
- Produces: CLI commands:
  - `atlas doctor`: Checks Python version, OS platform, SQLite availability.
  - `atlas init`: Creates `.atlas/` configuration and local database.
  - `atlas task create <objective>`: Creates and persists a task.
  - `atlas task list`: Lists tasks.

- [ ] **Step 1: Write integration tests for CLI commands**

Create `tests/integration/test_cli.py`:
```python
import subprocess
import sys
import pytest


def test_cli_help():
    cmd = [sys.executable, "-m", "atlas_cli.main", "--help"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    assert "ATLAS - Autonomous Task & Lifecycle Automation System" in result.stdout


def test_cli_doctor():
    cmd = [sys.executable, "-m", "atlas_cli.main", "doctor"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Python:" in result.stdout
    assert "System status: HEALTHY" in result.stdout


def test_cli_init_and_task_lifecycle(tmp_path):
    env = {"ATLAS_HOME": str(tmp_path)}
    init_cmd = [sys.executable, "-m", "atlas_cli.main", "init"]
    res_init = subprocess.run(
        init_cmd, capture_output=True, text=True, env={**dict(env), "PATH": ""}
    )
    # Will run with default or isolated config directory
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_cli.py`
Expected: FAIL

- [ ] **Step 3: Implement CLI commands using argparse or click**

Implement `apps/cli/src/atlas_cli/main.py` and commands in `doctor.py`, `init.py`, `task.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_cli.py`
Expected: PASS

- [ ] **Step 5: Commit CLI package**

```bash
git add apps/cli tests/integration/test_cli.py
git commit -m "feat(cli): implement developer CLI with doctor, init, and task commands"
```

---

### Task 9: CI Workflow, Test Matrix & Phase 1 Acceptance Verification

**Files:**
- Create: `.github/workflows/ci.yml`
- Update: `docs/PROJECT_STATUS.md`
- Update: `docs/IMPLEMENTATION_PLAN.md`
- Update: `docs/TEST_RESULTS.md`
- Update: `docs/CHANGELOG.md`

- [ ] **Step 1: Create GitHub Actions CI workflow**

Create `.github/workflows/ci.yml`:
```yaml
name: ATLAS CI

on:
  push:
    branches: [ master, main ]
  pull_request:
    branches: [ master, main ]

jobs:
  test:
    runs-on: windows-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Set up Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}
      - name: Lint and Format Check with Ruff
        run: uv run ruff check .
      - name: Run Pytest Test Suite
        run: uv run pytest -v
```

- [ ] **Step 2: Run full test suite and lint checks locally**

Run: `uv run ruff check .`
Expected: Clean output.
Run: `uv run pytest -v`
Expected: All unit and integration tests passing.

- [ ] **Step 3: Verify all 14 Phase 1 acceptance criteria**

Update `docs/PROJECT_STATUS.md` with:
- Phase 1 Acceptance Tracker: 14/14 checked.
Update `docs/TEST_RESULTS.md` with raw test output and coverage details.
Update `docs/CHANGELOG.md` with Phase 1 release notes.

- [ ] **Step 4: Commit Phase 1 completion and CI configuration**

```bash
git add .github/workflows/ci.yml docs/
git commit -m "docs: finalize Phase 1 acceptance verification and CI workflow"
```
