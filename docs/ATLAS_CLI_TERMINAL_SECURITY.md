# ATLAS CLI — Terminal Execution & Process Security

## 1. Threat Model & Invariants

Autonomous agents interacting with developer command lines introduce severe risks of command injection, remote code execution, accidental data destruction, and credential harvesting.

The `AuthorizedTerminalDriver` (`atlas_coding.terminal`) implements strict defense-in-depth:

1. **No Direct Shell String Execution**: Commands are parsed and passed as argument vectors (`argv: list[str]`) with `shell=False`. This eliminates standard shell metacharacter injection (`|`, `;`, `&&`, `` ` ``).
2. **Action Firewall Gate**: Every proposed execution is evaluated as a `terminal.execute` action.
3. **Destructive Command Pattern Detection**: Commands containing recursive deletions (`rm -rf`, `Remove-Item -Recurse`), disk formatting (`format C:`, `mkfs`), raw disk writing (`dd if=`), or fork bombs are intercepted and blocked or gated by approval rules.
4. **Credential and Secret Redaction**: Output streams (stdout and stderr) are filtered against regular expressions matching bearer tokens, API keys, passwords, and secrets, replacing them with `[REDACTED_SECRET]` before storage or model exposure.
5. **Execution Timeouts**: Subprocesses are bounded by strict execution limits (default 60s, hard maximum 600s). Timed-out processes are terminated and return exit code `124`.
6. **Workspace Containment**: The working directory (`cwd`) is verified to reside strictly within `repo_root`.

---

## 2. Policy Evaluation Flow

```
Agent Proposes Command
       │
       ▼
Normalize to argv list & validate target CWD
       │
       ▼
Construct ComputerAction(action_type="terminal.execute", ...)
       │
       ▼
ActionFirewall.evaluate(action)
   ├── Destructive command detected? ──► Gate with REQUIRE_APPROVAL
   ├── Custom user policy matches?   ──► Enforce policy decision
   └── Built-in category rule        ──► Default terminal gating
       │
       ▼
Subprocess Execution (shell=False, capture_output=True, timeout=T)
       │
       ▼
Secret Redaction Regex Filter on stdout / stderr
       │
       ▼
Synthesize TerminalResult(exit_code, stdout, stderr, duration, timed_out)
```

---

## 3. TerminalResult Schema

```python
class TerminalResult(BaseModel):
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    cwd: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
```
