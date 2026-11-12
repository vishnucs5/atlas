# ATLAS (Autonomous Task & Lifecycle Automation System)

> **"The model makes decisions. ATLAS controls execution."**

ATLAS is an independent, model-agnostic computer-use runtime designed to orchestrate AI agents operating across web browsers, desktop applications, and operating systems. The AI model never possesses unrestricted operating system, network, or credential access. All agent intentions are translated into standardized, versioned action requests that pass through runtime authorization, verification, and transactional event sourcing.

---

## Architectural Principles

1. **Architecture Ownership**: Core owns orchestration, lifecycle, and tool contracts. Low-level drivers implement interfaces; they never own planning or planning state.
2. **Action Firewall**: The model makes decisions; ATLAS controls execution. No model adapter or execution worker may execute an action without authorization.
3. **Zero-Dependency Core**: `packages/atlas-core` has zero dependencies on external operating system libraries, model providers, or database drivers.
4. **Finite State Machine**: Strict 14-state task lifecycle rejecting invalid transitions with deterministic validation.
5. **Event-Sourced Persistence**: Every mutation emits an immutable, strictly sequenced `ExecutionEvent`.
6. **Deterministic Verification**: Actions are never declared successful without empirical post-condition proof.
7. **Secret Sanitization**: High-performance streaming masking of sensitive credentials, API keys, and tokens.
8. **Target Platform**: Windows 11 first-class support with cross-platform abstractions.

---

## Monorepo Structure

ATLAS is organized as a Python `uv` workspace:

```
atlas-runtime/
├── packages/
│   ├── atlas-core/           # Domain entities, Pydantic v2 contracts, lifecycle state machine
│   ├── atlas-storage/        # Event store, SQLite (WAL) engine, PostgreSQL interface
│   ├── atlas-policy/         # Action Firewall, permission engine, human approval gating
│   └── atlas-observability/  # Structured JSON logging, contextual traces, secret masking
├── apps/
│   ├── api/                  # FastAPI runtime server, health and status endpoints
│   └── cli/                  # Developer CLI (`atlas doctor`, `atlas init`, `atlas task`)
├── docs/                     # Technical architecture, ADRs, and continuity documentation
│   ├── ARCHITECTURE.md       # Full architectural specification
│   ├── DECISIONS.md          # Architectural decision register
│   ├── IMPLEMENTATION_PLAN.md# Master implementation roadmap
│   ├── PROJECT_STATUS.md     # Current phase and task status
│   ├── TEST_RESULTS.md       # Test matrix and verification records
│   ├── KNOWN_ISSUES.md       # Known issues, technical debt, and workarounds
│   ├── CHANGELOG.md          # Version history and releases
│   └── adr/                  # Architectural Decision Records (ADRs)
├── tests/                    # Unit and integration test suites
├── AGENTS.md                 # Mandatory engineering constitution
├── pyproject.toml            # Root workspace configuration
└── ruff.toml                 # Workspace code style & lint rules
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Windows 11 (or Linux/macOS)

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd happy-meitner

# Sync workspace dependencies
uv sync

# Run workspace test suite
uv run pytest

# Check code formatting and linting
uv run ruff check .
```

### Developer CLI

```bash
# Diagnose environment health (Python, SQLite, OS, directories)
uv run atlas doctor

# Initialize local workspace and configuration
uv run atlas init

# Create and inspect tasks
uv run atlas task create --objective "Automate browser login"
uv run atlas task list
```

---

## Documentation

- [Engineering Constitution](AGENTS.md)
- [Architecture Overview](docs/ARCHITECTURE.md)
- [Architectural Decision Records (ADRs)](docs/DECISIONS.md)
  - [ADR-0001: Monorepo and Runtime Ownership](docs/adr/0001-monorepo-and-runtime-ownership.md)
  - [ADR-0002: Event-Sourced Task Persistence](docs/adr/0002-event-sourced-task-persistence.md)
  - [ADR-0003: Action Firewall and Policy Separation](docs/adr/0003-action-firewall-policy-separation.md)
- [Implementation Plan](docs/IMPLEMENTATION_PLAN.md)
- [Project Status](docs/PROJECT_STATUS.md)
- [Test Results](docs/TEST_RESULTS.md)
- [Known Issues & Constraints](docs/KNOWN_ISSUES.md)

---

## License

Proprietary - All rights reserved.
