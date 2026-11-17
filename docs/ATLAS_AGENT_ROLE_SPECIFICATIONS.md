# ATLAS Specialist Engineering Agent Role Specifications

## 1. Governance and Authority Principles

Every specialist agent in ATLAS operates under deterministic operational boundaries:
- **Least Privilege**: Capabilities declare what an agent is suited to do, not elevated system privileges.
- **Firewall Gate**: Every action proposal (`file.write`, `terminal.execute`) must pass Action Firewall policy evaluation.
- **Resource Envelope**: Tokens, dollar costs, and steps are capped via `AgentBudget`.
- **Failure Gating**: Failures propagate as structured exceptions; agents never swallow errors or invent synthetic success.

---

## 2. Comprehensive Role Definitions

### 1. Software Architect (`ARCHITECT`)
- **Responsibility**: System architecture, module decomposition, layer separation, invariant preservation.
- **Tools**: Read-only repository exploration, AST structure inspection.
- **Context Scope**: `PROJECT_SCOPED` architecture specifications.
- **Output Contract**: Structured dictionary with `module_boundaries`, `invariants_checked`, `status`.
- **Success Criteria**: Zero architectural boundary violations identified.

### 2. Repository Explorer (`EXPLORER`)
- **Responsibility**: Rapid file topology discovery, symbol extraction, test fixture mapping.
- **Tools**: `RepositoryExplorer`, `CodeSearchEngine`, `DependencyGraph`.
- **Context Scope**: `TASK_SCOPED` discovery summaries.
- **Output Contract**: `total_files_discovered`, `sample_files`, `topology_summary`.
- **Success Criteria**: Discovered files strictly bounded within workspace root.

### 3. Backend Engineer (`BACKEND`)
- **Responsibility**: Server APIs, controllers, services, data models, business logic.
- **Tools**: `AuthorizedFileOperations`, `PatchEngine`.
- **Context Scope**: `TASK_SCOPED` file write artifacts.
- **Output Contract**: `component: backend`, `file_path`, `lines_written`, `status: IMPLEMENTED`.
- **Success Criteria**: Syntactically valid code with zero hardcoded credentials.

### 4. Frontend Engineer (`FRONTEND`)
- **Responsibility**: User interface components, styling, client-side routing, accessibility.
- **Tools**: `AuthorizedFileOperations`, `PatchEngine`.
- **Context Scope**: `TASK_SCOPED` UI artifacts.
- **Output Contract**: `component: frontend`, `file_path`, `lines_written`, `status: IMPLEMENTED`.
- **Success Criteria**: Accessible components conforming to design specifications.

### 5. Database Engineer (`DATABASE`)
- **Responsibility**: Relational/NoSQL schemas, data migrations, SQL optimization, indexes.
- **Tools**: `AuthorizedFileOperations`, schema validators.
- **Context Scope**: `TASK_SCOPED` migration records.
- **Output Contract**: `migration_file`, `schema_verified: True`, `status: MIGRATION_READY`.
- **Success Criteria**: Reversible, idempotent SQL migration scripts.

### 6. Infrastructure Engineer (`INFRASTRUCTURE`)
- **Responsibility**: Dockerfiles, CI/CD pipelines, container orchestration, build environments.
- **Tools**: `AuthorizedFileOperations`, `AuthorizedTerminalDriver`.
- **Context Scope**: `TASK_SCOPED` infrastructure configurations.
- **Output Contract**: `config_path`, `environment_validated: True`, `status: CONFIGURED`.
- **Success Criteria**: Hermetic, reproducible build and execution definitions.

### 7. Testing Engineer (`TESTING`)
- **Responsibility**: Test suite authoring, test execution, regression verification, coverage reporting.
- **Tools**: `AuthorizedFileOperations`, `TestRunner`, `AuthorizedTerminalDriver`.
- **Context Scope**: `TASK_SCOPED` test result summaries.
- **Output Contract**: `test_file`, `results` (`tests_run`, `passed`, `failed`, `verdict`).
- **Success Criteria**: 100% test pass rate on target deliverables.

### 8. Security Auditor (`SECURITY_AUDITOR`)
- **Responsibility**: Secret leak scanning, prompt injection detection, Action Firewall rule validation.
- **Tools**: Sensitive file patterns, injection regex scanner, Action Firewall policy decider.
- **Context Scope**: `TASK_SCOPED` security audit reports.
- **Output Contract**: `findings_count`, `findings`, `firewall_compliance: bool`, `verdict: PASS/FAIL`.
- **Success Criteria**: Zero high or critical security vulnerabilities detected.

### 9. Code Reviewer (`CODE_REVIEWER`)
- **Responsibility**: Adversarial inspection of unified diffs, test evidence, requirements, and invariants.
- **Tools**: `IndependentCodeReviewer`, unified diff parser.
- **Context Scope**: `TASK_SCOPED` code review audits.
- **Output Contract**: `verdict: APPROVED/REJECTED`, `actionable_findings`, `diff_lines_inspected`.
- **Success Criteria**: Deterministic, evidence-based approval without superficial confirmation.

### 10. Documentation Engineer (`DOCUMENTATION`)
- **Responsibility**: User guides, API references, architecture decision records, markdown manuals.
- **Tools**: `AuthorizedFileOperations`, docstring extractors.
- **Context Scope**: `TASK_SCOPED` documentation artifacts.
- **Output Contract**: `doc_path`, `lines_written`, `status: DOCUMENTED`.
- **Success Criteria**: Complete and accurate documentation matching implementation contracts.

### 11. Debugging Engineer (`DEBUGGING`)
- **Responsibility**: Root-cause analysis, reproduction test fixtures, stack trace diagnosis, bugfix patches.
- **Tools**: `AuthorizedFileOperations`, `PatchEngine`, `TestRunner`, `AuthorizedTerminalDriver`.
- **Context Scope**: `TASK_SCOPED` debug resolutions.
- **Output Contract**: `root_cause`, `patch_file`, `repro_fixture`, `status: RESOLVED`.
- **Success Criteria**: Failing reproduction test converted to passing via targeted patch.
