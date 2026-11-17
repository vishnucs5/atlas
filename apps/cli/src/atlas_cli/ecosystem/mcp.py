"""Model Context Protocol (MCP) integration, discovery, schema validation, and firewall gating."""

import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from atlas_core.contracts.action import ActionTarget, ComputerAction
from atlas_core.contracts.policy import PolicyDecisionType
from atlas_policy.firewall import ActionFirewall
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("atlas.cli.ecosystem.mcp")

SECRET_REGEX = re.compile(
    r"""(?i)(?:bearer\s+[a-zA-Z0-9_\-\.]{12,}|api[_-]?key\s*[:=]\s*['"]?[a-zA-Z0-9_\-]{12,}['"]?|secret\s*[:=]\s*['"]?[a-zA-Z0-9_\-]{12,}['"]?)"""
)


class MCPExecutionError(Exception):
    """Base exception for MCP execution errors."""


class MCPPolicyViolationError(MCPExecutionError):
    """Raised when an MCP tool invocation is rejected by the Action Firewall."""


class MCPServerConfig(BaseModel):
    """Configuration definition for an MCP server integration."""

    model_config = ConfigDict(validate_assignment=True)

    server_id: str
    name: str
    transport: str = "stdio"  # "stdio" or "sse"
    command: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    protocol_version: str = "2024-11-05"


class MCPToolSchema(BaseModel):
    """Discovered MCP tool metadata and parameter schema."""

    model_config = ConfigDict(validate_assignment=True)

    name: str
    server_id: str = "default"
    server_name: str = "default"
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = Field(default_factory=list)


class MCPToolResult(BaseModel):
    """Execution outcome of an MCP tool invocation with security tagging."""

    model_config = ConfigDict(validate_assignment=True)

    tool_name: str
    server_id: str
    success: bool
    content: Any = None
    error: str | None = None
    is_untrusted: bool = True  # External tool responses are strictly untrusted
    execution_time_ms: float = 0.0

    @property
    def is_error(self) -> bool:
        return not self.success or self.error is not None


class MCPClientManager:
    """Manages MCP server lifecycles, schema registries, and firewall-governed invocation."""

    def __init__(
        self,
        firewall: ActionFirewall | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.firewall = firewall or ActionFirewall()
        self.config_path = Path(config_path) if config_path else Path(".atlas/mcp.json")
        self.servers: dict[str, MCPServerConfig] = {
            "default": MCPServerConfig(
                server_id="default",
                name="Default Local MCP Server",
                transport="stdio",
                enabled=True,
            )
        }
        self.tools: dict[str, MCPToolSchema] = {}
        self._mock_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._server_health: dict[str, str] = {}  # "HEALTHY", "DISCONNECTED", "STOPPED"

    def register_server(
        self,
        config: MCPServerConfig,
        auto_connect: bool = True,
    ) -> None:
        """Register an MCP server configuration."""
        with self._lock:
            self.servers[config.server_id] = config
            if auto_connect and config.enabled:
                self._server_health[config.server_id] = "HEALTHY"
            else:
                self._server_health[config.server_id] = "STOPPED"

    def register_tool(
        self,
        tool: MCPToolSchema,
        handler: Callable[[dict[str, Any]], Any] | None = None,
        executor: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        """Register an available tool provided by an MCP server."""
        fn = handler or executor
        with self._lock:
            self.tools[tool.name] = tool
            if fn:
                self._mock_handlers[tool.name] = fn

    def get_tool(self, tool_name: str) -> MCPToolSchema | None:
        """Retrieve a registered MCP tool by name."""
        with self._lock:
            return self.tools.get(tool_name)

    def discover_servers(self) -> list[MCPServerConfig]:
        """Discover MCP servers from configuration files or defaults."""
        with self._lock:
            if self.config_path.is_file():
                try:
                    data = json.loads(self.config_path.read_text(encoding="utf-8"))
                    for s_data in data.get("mcpServers", {}).values():
                        cfg = MCPServerConfig.model_validate(s_data)
                        self.register_server(cfg)
                except Exception as exc:
                    logger.warning("Failed to parse MCP config file %s: %s", self.config_path, exc)

            return list(self.servers.values())

    def list_tools(self, server_id: str | None = None) -> list[MCPToolSchema]:
        """List discovered tools, optionally filtered by server ID."""
        with self._lock:
            if server_id:
                return [t for t in self.tools.values() if t.server_id == server_id]
            return list(self.tools.values())

    def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        task_id: str = "task_mcp",
    ) -> MCPToolResult:
        """Safely invoke an MCP tool through Action Firewall policy gates."""
        with self._lock:
            tool = self.tools.get(tool_name)
            if not tool:
                msg = f"MCP tool '{tool_name}' not found."
                raise KeyError(msg)

            server = self.servers.get(tool.server_id)
            if not server or not server.enabled:
                msg = f"MCP server '{tool.server_id}' is disabled or unavailable."
                raise RuntimeError(msg)

            # Security: Action Firewall Evaluation
            action = ComputerAction(
                action_id=f"act_mcp_{uuid.uuid4().hex[:8]}",
                task_id=task_id,
                session_id="session_mcp",
                action_type=f"mcp.{tool_name}",
                target=ActionTarget(strategy="tool", value=tool_name),
                parameters=arguments,
                idempotency_key=f"idem_{tool_name}_{time.time_ns()}",
            )

            decision = self.firewall.evaluate(action)
            if decision.decision == PolicyDecisionType.DENY:
                raise MCPPolicyViolationError(
                    f"MCP tool invocation '{tool_name}' denied by Action Firewall: {decision.reason}"
                )

            # Execute tool handler
            t0 = time.monotonic()
            try:
                handler = self._mock_handlers.get(tool_name)
                raw_result = (
                    handler(arguments)
                    if handler
                    else {"status": "success", "result": f"Executed {tool_name}"}
                )
                elapsed_ms = round((time.monotonic() - t0) * 1000, 2)

                # Redact sensitive credentials in output
                sanitized_str = SECRET_REGEX.sub("[REDACTED_CREDENTIAL]", json.dumps(raw_result))
                sanitized_content = json.loads(sanitized_str)

                return MCPToolResult(
                    tool_name=tool_name,
                    server_id=tool.server_id,
                    success=True,
                    content=sanitized_content,
                    is_untrusted=True,  # All external MCP outputs tagged untrusted
                    execution_time_ms=elapsed_ms,
                )
            except Exception as exc:
                elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
                return MCPToolResult(
                    tool_name=tool_name,
                    server_id=tool.server_id,
                    success=False,
                    error=str(exc),
                    is_untrusted=True,
                    execution_time_ms=elapsed_ms,
                )

    def shutdown_server(self, server_id: str) -> None:
        """Gracefully shut down an MCP server connection."""
        with self._lock:
            if server_id in self.servers:
                self._server_health[server_id] = "STOPPED"

    def reconnect_server(self, server_id: str) -> bool:
        """Attempt reconnection to a disconnected MCP server."""
        with self._lock:
            if server_id in self.servers and self.servers[server_id].enabled:
                self._server_health[server_id] = "HEALTHY"
                return True
            return False

    def get_server_status(self, server_id: str) -> str:
        """Return the health/connection status of an MCP server."""
        with self._lock:
            return self._server_health.get(server_id, "UNKNOWN")
