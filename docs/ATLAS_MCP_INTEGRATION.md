# ATLAS Model Context Protocol (MCP) Integration Architecture

## 1. Overview and Core Philosophy

The Model Context Protocol (MCP) integration in ATLAS CLI provides a standard mechanism for connecting external tools and servers to the autonomous engineering runtime. Unlike naive agent harnesses that grant raw external tool execution or execute tool instructions unchecked, ATLAS treats all MCP components as untrusted external integrations subject to the **Action Firewall** and zero-dependency core architectural invariants.

```
┌────────────────────────────────────────────────────────┐
│                      ATLAS CLI                         │
│                                                        │
│  ┌───────────────────┐        ┌─────────────────────┐  │
│  │   Agent / Model   │───────>│   MCPClientManager  │  │
│  └───────────────────┘        └──────────┬──────────┘  │
│                                          │             │
│                               ┌──────────▼──────────┐  │
│                               │   Action Firewall   │  │
│                               │ (Policy Enforcement)│  │
│                               └──────────┬──────────┘  │
│                                          │             │
│       ┌──────────────────────────────────┴─────┐       │
│       ▼                                        ▼       │
│  [stdio Transport]                        [sse Transport]
│  External Server                          Remote Gateway
└────────────────────────────────────────────────────────┘
```

---

## 2. Server Discovery and Registration

ATLAS supports two standard discovery modes for MCP servers:

1. **Local Configuration File (`.atlas/mcp.json`)**:
   Standard project-level or global JSON declaration defining stdio/SSE servers.
   ```json
   {
     "mcpServers": {
       "science_biomolecular_viewer": {
         "command": ["python", "-m", "science_viewer_mcp"],
         "transport": "stdio",
         "enabled": true
       },
       "gemini_docs": {
         "url": "https://api.docs.example.com/sse",
         "transport": "sse",
         "enabled": true
       }
     }
   }
   ```

2. **Programmatic Registration**:
   Via `MCPClientManager.register_server(MCPServerConfig(...))`.

---

## 3. Tool Discovery and Schema Validation

Discovered tools are parsed into `MCPToolSchema` instances conforming to Pydantic validation:
- Tool parameters and argument types are validated against JSON Schema definitions.
- Missing required fields immediately abort execution before model invocation.
- Secret redaction is applied to all incoming parameters (`SECRET_REGEX` scrubbing tokens, keys, and passwords).

---

## 4. Action Firewall Authorization Invariant

Every MCP tool invocation is mapped to an authoritative `ComputerAction` with namespace `mcp.<tool_name>`.
Execution must be approved by the `ActionFirewall`:
- If an exact action type rule (e.g. `mcp.dangerous_calc`) or category rule evaluates to `DENY`, the invocation is immediately aborted and an `MCPPolicyViolationError` is raised.
- Prompts, tool descriptions, or docstrings cannot override or grant firewall permissions.

---

## 5. Untrusted Response Tagging and Credential Scrubbing

External MCP tools run outside the ATLAS core trusted perimeter. Therefore:
- All tool execution outputs are explicitly tagged with `is_untrusted: True`.
- Outputs are scanned and masked by `SECRET_REGEX` prior to injection into agent conversation context.
- Exceptions during transport communication (pipe breakage, network disconnect, SSE timeout) are converted into structured `MCPToolResult` error envelopes without leaking stack traces or host environment variables.
