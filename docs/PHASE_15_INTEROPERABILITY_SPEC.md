# ATLAS Phase 15 External Interoperability Specification
## Model Context Protocol (MCP) & Webhook Integration

---

## 1. Model Context Protocol (MCP) Adapter

ATLAS Phase 15 introduces standard MCP client and server bridges allowing external MCP-compatible agents to discover ATLAS capabilities and invoke scoped tools under local policy supervision:

```python
class MCPToolAdapter:
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_permissions: list[str]
    timeout_ms: int = 30000
```

### 1.1 Policy Enforcement at the MCP Boundary
- Every external MCP `call_tool` request is intercepted by the local `ActionFirewall`.
- If the tool parameters violate local policy (e.g. unauthorized destination domain, destructive file operation), the MCP adapter returns a standardized MCP error response: `{"isError": true, "content": [{"type": "text", "text": "Action blocked by ActionFirewall"}]}`.

---

## 2. HTTP & Webhook Integration Adapter

For external workflow engines (e.g. Zapier, Airflow, GitHub Actions):
- **Signed Webhook Ingestion**: Inbound HTTP requests require HMAC-SHA256 signature verification in the `X-Atlas-Signature` header.
- **Contract Mapping**: External JSON payloads are converted into standard `TaskProposal` contracts with explicit deadlines and data sensitivity tags.
- **Result Callback**: Upon task completion and evidence validation, a signed asynchronous webhook callback is dispatched to the external caller.
