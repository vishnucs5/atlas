# Changelog

All notable changes to the ATLAS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0-alpha] - 2026-11-12

### Added
- Root monorepo workspace configuration using `uv` (`pyproject.toml`) linking packages (`atlas-core`, `atlas-storage`, `atlas-policy`, `atlas-observability`) and apps (`apps/api`, `apps/cli`).
- Code style and linting configuration in `ruff.toml` targeting Python 3.11+.
- Comprehensive `.gitignore` filtering out bytecode, test caches, virtual environments, and SQLite databases.
- Engineering Constitution (`AGENTS.md`) enforcing 8 mandatory rules for contributors and AI agents.
- Comprehensive root `README.md` introducing ATLAS architecture, philosophy, and getting started guide.
- Technical architecture specification in `docs/ARCHITECTURE.md`.
- Architectural Decisions log in `docs/DECISIONS.md`.
- Master Implementation Plan in `docs/IMPLEMENTATION_PLAN.md`.
- Project Status tracking in `docs/PROJECT_STATUS.md`.
- Test Results & Verification Ledger in `docs/TEST_RESULTS.md`.
- Known Issues & Constraints tracking in `docs/KNOWN_ISSUES.md`.
- Foundational Architectural Decision Records:
  - `docs/adr/0001-monorepo-and-runtime-ownership.md`: Monorepo Workspace and Runtime Ownership.
  - `docs/adr/0002-event-sourced-task-persistence.md`: Event-Sourced Task Persistence.
  - `docs/adr/0003-action-firewall-policy-separation.md`: Action Firewall & Policy Engine Separation.
