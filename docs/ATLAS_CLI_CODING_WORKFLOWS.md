# ATLAS CLI — Coding Workflows & Operator Manual

## 1. CLI Commands Reference

ATLAS CLI provides developer commands designed for day-to-day software engineering:

### 1. Direct Autonomous Coding
```bash
# Execute autonomous engineering goal
atlas "Add health check endpoint with JSON status and uptime"
```
Orchestrates:
- Task creation (`CodingTask`)
- Repository manifest and file discovery
- Step planning and risk classification
- Action Firewall evaluation
- File modification and patch application
- Test execution and post-condition verification

### 2. Planning Without Execution
```bash
# Synthesize structured multi-step plan
atlas plan "Refactor authentication service to JWT"
```
Outputs:
- Target files and detected manifests
- Step-by-step decomposition
- Risk badges (`[LOW]`, `[HIGH]`, `[CRITICAL]`)
- Approval requirements

### 3. Repository Review & Diffs
```bash
# Inspect working tree status
atlas review

# Display colored unified diff of modified files
atlas review --diff
```
Inspects:
- Current branch
- Modified, staged, untracked, and deleted files
- Action Firewall violation audit

### 4. Diagnostic Debugging
```bash
# Run workspace diagnostics
atlas debug
```
Checks:
- Static analysis & linting (`ruff check`)
- Python runtime environment
- Storage health (SQLite WAL)

### 5. Deterministic QA & Testing
```bash
# Auto-detect test framework and execute test suite
atlas test
```
Capabilities:
- Auto-detects `pytest`, `npm test`, `cargo test`, `go test`
- Synthesizes structured test metrics (passed, failed, skipped, duration)
- Verifies deterministic assertion success

---

## 2. Governance and Safety Commands

```bash
# Check system status
atlas status

# Run diagnostic verification
atlas doctor

# Inspect active sessions
atlas sessions list

# View active approvals
atlas approvals
```
