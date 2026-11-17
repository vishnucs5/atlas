# ATLAS CLI Command Reference

Comprehensive syntax, arguments, options, and exit codes for all ATLAS CLI subcommands.

---

## Global Options

- `--minimal`: Launch in headless, scriptable, minimal interactive mode.
- `--tui`: Launch the 8-panel interactive Terminal User Interface.
- `--version`, `-v`: Display ATLAS CLI version metadata.
- `--help`, `-h`: Show contextual help message and exit.

---

## 1. System & Environment Commands

### `atlas doctor`
Inspect system prerequisites, OS compatibility, Python version, and SQLite capabilities.
```bash
atlas doctor
```

### `atlas init`
Initialize a local `.atlas/` control directory and database in the current workspace.
```bash
atlas init
```

### `atlas status`
Display cluster control plane, active tasks, worker fleet, and system health status.
```bash
atlas status
```

### `atlas edition`
Display product edition (`open-source` vs `enterprise`) and feature availability matrix.
```bash
atlas edition
```

---

## 2. Coding & Engineering Workflows

### `atlas "<objective>"`
Execute an autonomous coding task directly from a terminal prompt.
```bash
atlas "Implement healthcheck endpoint returning JSON uptime"
```

### `atlas plan "<goal>"`
Synthesize a structured engineering execution plan without applying code modifications.
```bash
atlas plan "Migrate PostgreSQL database connection pool to asyncpg"
```

### `atlas review [--diff]`
Perform an independent adversarial code review of the working tree or specific unified diff.
```bash
atlas review --diff
```

### `atlas test`
Execute project test suites using automated framework detection.
```bash
atlas test
```

### `atlas debug`
Analyze failed test outputs and generate reproduction hypotheses and minimal patches.
```bash
atlas debug
```

---

## 3. Extensibility & Ecosystem Commands

### `atlas skills list`
List registered engineering workflow skills, categories, and permission boundaries.
```bash
atlas skills list
```

### `atlas profiles list`
List workspace configuration profiles and privilege ceilings.
```bash
atlas profiles list
```

### `atlas plugins list`
List installed marketplace plugins, versions, publisher identities, and verification states.
```bash
atlas plugins list
```

### `atlas plugins install <name>`
Install and verify a signed marketplace plugin package.
```bash
atlas plugins install atlas-browser-pack
```

### `atlas mcp list`
List Model Context Protocol (MCP) servers, transport types, and registered tools.
```bash
atlas mcp list
```

---

## 4. Multi-Agent Team Commands

### `atlas agents list`
List the 11 specialized engineering agents in the ATLAS roster.
```bash
atlas agents list
```

### `atlas agents inspect <agent_name>`
Display a specialist agent's role description, capabilities, tool permissions, and context scope.
```bash
atlas agents inspect security_auditor
```

---

## 5. Governance & Approvals

### `atlas approval list`
List pending human-in-the-loop approval requests.
```bash
atlas approval list
```

### `atlas approval grant <request_id> [--reason <text>]`
Grant an approval request with cryptographic parameter binding.
```bash
atlas approval grant req_12345 --reason "Approved for staging deployment"
```

### `atlas approval deny <request_id> [--reason <text>]`
Deny an approval request and abort task execution.
```bash
atlas approval deny req_12345 --reason "Rejected: violates database security policy"
```

### `atlas permissions`
Display Action Firewall policy rules and exact permission boundaries.
```bash
atlas permissions
```

---

## Exit Codes

| Exit Code | Meaning |
| :---: | :--- |
| `0` | Success / Clean Completion |
| `1` | General Execution Failure / Test Regression |
| `2` | Command Line Syntax or Argument Error |
| `130` | Graceful User Interrupt (`Ctrl+C` / `SIGINT`) |
