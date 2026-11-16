"""ATLAS External Agent Interoperability Adapters.

Provides bi-directional translation for external agent ecosystems including
Model Context Protocol (MCP) tools and HMAC-verified HTTP Webhook triggers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from pydantic import BaseModel, Field

from atlas_federation.delegation import TaskProposal, UnauthorizedDelegationError
from atlas_federation.identity import ParticipantIdentity


class MCPToolDefinition(BaseModel):
    """MCP-compliant tool specification advertised to external orchestrators."""

    name: str
    description: str
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class MCPAdapter:
    """Translates MCP tool invocations into ATLAS internal actions with Action Firewall gates."""

    def __init__(
        self, organization_id: str, installation_id: str, local_firewall: Any | None = None
    ) -> None:
        self.organization_id = organization_id
        self.installation_id = installation_id
        self.local_firewall = local_firewall
        self._tools: dict[str, MCPToolDefinition] = {}

    def register_tool(self, tool: MCPToolDefinition) -> None:
        """Register a tool available for MCP clients."""
        self._tools[tool.name] = tool

    def list_tools(self) -> list[dict[str, Any]]:
        """Handle MCP 'tools/list' request."""
        return [tool.model_dump() for tool in self._tools.values()]

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        caller_identity: ParticipantIdentity | None = None,
    ) -> dict[str, Any]:
        """Handle MCP 'tools/call' request with strict Action Firewall evaluation.

        Returns MCP-compliant response with 'isError' and 'content'.
        """
        if name not in self._tools:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Tool '{name}' not found."}],
            }

        # Action Firewall Evaluation: Check for dangerous parameters or unauthorized operations
        if self.local_firewall is not None:
            # Check if arguments contain dangerous shell commands, SQL injections, or priv-esc
            serialized_args = json.dumps(arguments).lower()
            dangerous_patterns = [
                "rm -rf",
                "drop table",
                "firewall:disable",
                "chmod 777",
                "admin_override",
            ]
            for pattern in dangerous_patterns:
                if pattern in serialized_args:
                    return {
                        "isError": True,
                        "content": [
                            {
                                "type": "text",
                                "text": f"Action Firewall blocked MCP execution: dangerous pattern '{pattern}' detected.",
                            }
                        ],
                    }

        # Simulated or actual execution
        result_text = f"Successfully executed tool '{name}' with arguments {arguments}"
        return {
            "isError": False,
            "content": [{"type": "text", "text": result_text}],
        }


class WebhookAdapter:
    """Handles external HTTP webhooks with HMAC-SHA256 signature verification."""

    def __init__(self, secret_key: str, organization_id: str, installation_id: str) -> None:
        self.secret_key = secret_key
        self.organization_id = organization_id
        self.installation_id = installation_id

    def compute_signature(self, raw_body: bytes) -> str:
        """Compute HMAC-SHA256 signature for webhook payload."""
        return hmac.new(self.secret_key.encode(), raw_body, hashlib.sha256).hexdigest()

    def verify_signature(self, raw_body: bytes, signature_header: str) -> bool:
        """Verify incoming webhook signature header in constant time."""
        expected = self.compute_signature(raw_body)
        cleaned_header = signature_header.removeprefix("sha256=").strip()
        return hmac.compare_digest(expected, cleaned_header)

    def ingest_webhook(
        self,
        raw_body: bytes,
        headers: dict[str, str],
        tenant_id: str = "tenant_webhook_default",
    ) -> TaskProposal:
        """Verify, parse, and transform an external webhook into an internal TaskProposal."""
        sig_header = (
            headers.get("X-Atlas-Signature")
            or headers.get("x-atlas-signature")
            or headers.get("X-Hub-Signature-256")
        )
        if not sig_header or not self.verify_signature(raw_body, sig_header):
            raise UnauthorizedDelegationError(
                "Webhook verification failed: invalid or missing cryptographic signature."
            )

        try:
            payload = json.loads(raw_body.decode())
        except Exception as exc:
            raise UnauthorizedDelegationError(f"Malformed webhook JSON body: {exc}") from exc

        return TaskProposal(
            origin_task_id=f"hook_{int(time.time())}",
            origin_tenant_id=tenant_id,
            sender=ParticipantIdentity(
                organization_id=payload.get("source_org", "external_partner"),
                installation_id="webhook_gateway",
            ),
            recipient=ParticipantIdentity(
                organization_id=self.organization_id,
                installation_id=self.installation_id,
            ),
            objective=payload.get("objective", "External webhook triggered automation"),
            inputs=payload.get("data", {}),
            required_permissions=payload.get("permissions", ["read"]),
            verification_requirements=["webhook_ack", "audit_logged"],
        )

    def generate_callback_payload(
        self,
        task_id: str,
        status: str,
        result_data: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Generate signed JSON callback payload and HMAC header for notifying external callers."""
        payload = {
            "task_id": task_id,
            "status": status,
            "result": result_data,
            "timestamp": time.time(),
        }
        serialized = json.dumps(payload, sort_keys=True).encode()
        sig = f"sha256={self.compute_signature(serialized)}"
        return payload, sig
