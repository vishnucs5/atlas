# ATLAS CLI — Keyboard Navigation & Shortcuts Reference

## 1. Advanced TUI Shortcuts

When running the interactive dashboard (`atlas --tui`):

| Key / Command | Action | Scope |
|---|---|---|
| `1` | Switch focus to **Main Conversation** panel | Global |
| `2` | Switch focus to **Agent Activity** panel | Global |
| `3` | Switch focus to **Task Graph** panel | Global |
| `4` | Switch focus to **Authorized Terminal** panel | Global |
| `5` | Switch focus to **File Changes & Diffs** panel | Global |
| `6` | Switch focus to **Action Firewall Approvals** panel | Global |
| `7` | Switch focus to **Execution Event Timeline** panel | Global |
| `8` | Switch focus to **Runtime & Resource Monitor** panel | Global |
| `tab` | Cycle to the next panel in sequence | Global |
| `switch <1-8>` | Explicitly navigate to target panel index | Command Bar |
| `run <goal>` | Submit software engineering objective to Coding Engine | Command Bar |
| `a` | Open interactive approval dialog for pending requests | Global |
| `r` | Refresh cluster telemetry and task data | Global |
| `q`, `quit`, `exit` | Cleanly exit TUI dashboard | Global |
| `Ctrl+C` | Cancel current interactive turn (preserves durable tasks) | Global |

---

## 2. Minimal Mode Shortcuts & Slash Commands

When running in minimal mode (`atlas`, `atlas --minimal`):

| Slash Command | Parameter | Function |
|---|---|---|
| `/help` | — | Display complete command reference and usage examples |
| `/diff` | — | Display unified git diff of working tree changes |
| `/status` | — | Display current branch and untracked/modified files |
| `/plan` | `<goal>` | Synthesize structured execution plan with risk levels |
| `/test` | — | Discover test framework and run repository test suite |
| `/approvals` | — | Interactively authorize or deny pending firewall actions |
| `/sessions` | — | List saved session identifiers |
| `/resume` | `<session_id>` | Restore conversation history from existing session |
| `/clear` | — | Clear terminal screen and redraw welcome banner |
| `/exit`, `/quit` | — | Cleanly terminate minimal REPL session |
| `Ctrl+C` | — | Cancel current turn input without cancelling durable background work |

---

## 3. Accessibility & Terminal Dimension Handling

- **Minimum Dimensions**: 80 columns by 24 lines.
- **Degraded Dimensions Alert**: When the terminal window is resized below 80x24, the TUI displays a clear alert requesting window expansion or recommending fallback to `atlas --minimal`.
- **Text-Only Stream Mode**: For screen readers or low-bandwidth serial lines, `atlas --minimal` operates without ANSI escape codes when terminal color support is disabled.
