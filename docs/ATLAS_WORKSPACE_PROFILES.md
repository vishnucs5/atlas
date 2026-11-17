# ATLAS Workspace Profiles Specification

## 1. Purpose

Workspace Profiles allow ATLAS CLI to configure tool selections, linter settings, test runners, and context window token allocations according to the active repository type without manual developer configuration.

Critically, **workspace profiles cannot elevate user privileges**. A profile defines a privilege ceiling; if a profile requests permissions beyond the authenticated user's authorization level, switching to that profile is blocked by the runtime.

---

## 2. Standard Built-In Profiles

ATLAS CLI includes 6 specialized built-in workspace profiles:

1. **`python-dev` (Python Development)**:
   - *Languages*: Python
   - *Test Command*: `pytest`
   - *Format & Lint*: `ruff format .`, `ruff check .`
   - *Context Tokens*: 8,000
   - *Privilege Ceiling*: `STANDARD_USER`

2. **`typescript-dev` (TypeScript & Web Development)**:
   - *Languages*: TypeScript, JavaScript
   - *Test Command*: `npm test`
   - *Format & Lint*: `prettier --write .`, `eslint .`
   - *Context Tokens*: 8,000
   - *Privilege Ceiling*: `STANDARD_USER`

3. **`java-backend` (Java Backend Development)**:
   - *Languages*: Java
   - *Test Command*: `mvn test`
   - *Format & Lint*: `mvn spotless:apply`, `mvn checkstyle:check`
   - *Context Tokens*: 8,000
   - *Privilege Ceiling*: `STANDARD_USER`

4. **`machine-learning` (Machine Learning & Data Science)**:
   - *Languages*: Python
   - *Test Command*: `pytest`
   - *Tools*: `file.read`, `file.write`, `terminal.execute`, `data.analyze`
   - *Context Tokens*: 16,000 (high-capacity context budget)
   - *Privilege Ceiling*: `STANDARD_USER`

5. **`infrastructure` (DevOps & Infrastructure Automation)**:
   - *Languages*: Dockerfile, YAML, Terraform
   - *Test Command*: `docker build .`
   - *Format & Lint*: `terraform fmt`, `hadolint Dockerfile`
   - *Context Tokens*: 8,000
   - *Privilege Ceiling*: `STANDARD_USER`

6. **`security-review` (Security Audit & Vulnerability Assessment)**:
   - *Languages*: Python, TypeScript, Go, Rust
   - *Test Command*: `pip-audit`
   - *Tools*: `file.read`, `security.audit`, `policy.evaluate`
   - *Context Tokens*: 6,000
   - *Privilege Ceiling*: `STANDARD_USER`

---

## 3. Automatic Detection & Manifest Matching

The `WorkspaceProfileManager.detect_profile(repo_root)` method automatically detects project type by inspecting repository manifests:

- `package.json` or `tsconfig.json` → `typescript-dev`
- `pom.xml` or `build.gradle` → `java-backend`
- `Dockerfile` (without `pyproject.toml`) → `infrastructure`
- `pyproject.toml` or `setup.py` → `python-dev`

---

## 4. Privilege Boundary Ceiling Enforcing

Profiles are constrained by the user's authenticated RBAC identity:
```
           Privilege Ceiling Hierarchy:
ROOT_ADMIN (4) > ADMIN_ELEVATED (3) > STANDARD_USER (2) > RESTRICTED (1)
```

If `req_rank > user_rank`:
A `PrivilegeBoundaryViolationError` is raised. Workspace profiles cannot override or bypass security governance.
