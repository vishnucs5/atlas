# ATLAS Skill SDK & Prompt Defense Architecture

## 1. Overview

The ATLAS Skill SDK provides a structured, verifiable approach to authoring and executing engineering workflows. Skills decompose complex software engineering goals into deterministic steps, parameter contracts, and guarded execution callbacks.

Skills are protected against **adversarial prompt injections** and **policy override attacks** via strict instruction pre-screening and schema validation.

---

## 2. Standard Built-In Skills

ATLAS CLI ships with 7 verified engineering workflow skills:

| Skill ID | Name | Category | Primary Function |
| :--- | :--- | :--- | :--- |
| `skill_coding_workflow` | Coding Workflow | `CODE` | Module decomposition, patch synthesis, and test iteration. |
| `skill_debugging_workflow` | Debugging Workflow | `CODE` | Stack trace analysis, test reproduction, and minimal patch creation. |
| `skill_testing_workflow` | Testing Workflow | `QUALITY_ASSURANCE` | Test case generation, coverage analysis, and regression suite execution. |
| `skill_security_analysis` | Security Analysis | `SECURITY_AUDIT` | Vulnerability assessment, credential leak detection, and AST security scan. |
| `skill_documentation_workflow` | Documentation Workflow | `TEXT_PROCESSING`| Docstring extraction, architectural markdown generation, and API doc syncing. |
| `skill_repo_analysis` | Repository Analysis | `RESEARCH` | Repository topology, AST symbol indexing, and dependency graph mapping. |
| `skill_infra_operations` | Infrastructure Operations | `CODE` | Containerization, CI/CD workflow generation, and environment configuration. |

---

## 3. Adversarial Prompt Defense Invariant

External or user-submitted skill instructions can serve as indirect prompt injection vectors. The `SkillManager` runs regex-based heuristic and semantic scans against dangerous patterns before registering or executing any skill:

- `\bignore\s+(?:all\s+)?previous\s+instructions\b`
- `\boverride\s+(?:system\s+)?policy\b`
- `\bbypass\s+action\s+firewall\b`
- `\bgrant\s+root\s+privileges\b`

If any adversarial pattern is detected:
1. The skill is rejected with status `SkillTrustStatus.REJECTED`.
2. A `SkillValidationError` is raised.
3. The skill is excluded from model context and prevented from dispatching actions.

---

## 4. Parameter Schema Validation & Execution

Skills declare strictly-typed input parameters (`SkillParameter`). When a skill is executed via `SkillManager.execute_skill()`:
1. The skill must hold `SkillTrustStatus.VERIFIED` status.
2. All required parameters must be present and validated against the declared schema.
3. Execution time is recorded in milliseconds.
4. Execution logs and structured output are returned in an immutable `SkillResult` envelope.
