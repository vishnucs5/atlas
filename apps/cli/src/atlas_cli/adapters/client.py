"""ATLAS Client Adapter providing unified communication with local API server or embedded runtime."""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("atlas.cli.adapter")


class AtlasClient:
    """Client adapter connecting to ATLAS REST API with fallback to embedded storage."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 2.0,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("ATLAS_API_URL") or "http://127.0.0.1:8000"
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("ATLAS_API_KEY") or "admin-key"
        self.timeout = timeout

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        """Perform HTTP request against ATLAS server with authorization header."""
        url = f"{self.base_url}{endpoint}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}?{query}"

        body = json.dumps(data).encode("utf-8") if data is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                status_code = response.status
                raw = response.read().decode("utf-8")
                return status_code, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as http_err:
            raw = http_err.read().decode("utf-8")
            try:
                err_data = json.loads(raw)
            except Exception:
                err_data = {"detail": raw or str(http_err)}
            return http_err.code, err_data
        except Exception as exc:
            return 0, {"error": str(exc), "offline": True}

    def is_server_online(self) -> bool:
        """Check if ATLAS server is reachable."""
        code, data = self._request("/healthz")
        return code == 200 and data.get("status") in ("ok", "healthy")

    def get_server_health(self) -> dict[str, Any]:
        """Retrieve server health payload."""
        code, data = self._request("/healthz")
        return (
            data
            if code == 200
            else {"status": "offline", "error": data.get("error", "Unreachable")}
        )

    def list_tasks(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List tasks from server or local database."""
        code, data = self._request("/api/v1/tasks", params={"limit": limit, "offset": offset})
        if code == 200 and isinstance(data, list):
            return data
        return []

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve task details by ID."""
        code, data = self._request(f"/api/v1/tasks/{task_id}")
        return data if code == 200 else None

    def submit_task(
        self,
        objective: str,
        priority: str = "NORMAL",
        wait: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit a single task for autonomous execution."""
        payload = {"objective": objective, "priority": priority, "metadata": metadata or {}}
        code, data = self._request(
            f"/api/v1/tasks?wait={'true' if wait else 'false'}", method="POST", data=payload
        )
        return (
            data if code in (200, 201) else {"error": data.get("detail") or "Failed to submit task"}
        )

    def submit_multi_agent_dag(
        self,
        objective: str,
        max_parallel: int = 4,
        execute_async: bool = False,
    ) -> dict[str, Any]:
        """Dispatch a multi-agent DAG task across specialist agents."""
        payload = {
            "objective": objective,
            "max_parallel": max_parallel,
            "execute_async": execute_async,
        }
        code, data = self._request("/api/v1/orchestration/tasks", method="POST", data=payload)
        return (
            data
            if code in (200, 201)
            else {"error": data.get("detail") or "Failed to dispatch DAG task"}
        )

    def list_multi_agent_tasks(self) -> list[dict[str, Any]]:
        """List multi-agent DAG tasks."""
        code, data = self._request("/api/v1/orchestration/tasks")
        return data if code == 200 and isinstance(data, list) else []

    def list_agents(self) -> list[dict[str, Any]]:
        """List autonomous specialist agents."""
        code, data = self._request("/api/v1/orchestration/agents")
        return data if code == 200 and isinstance(data, list) else []

    def list_approvals(self, status: str | None = None) -> list[dict[str, Any]]:
        """List Action Firewall approval requests."""
        params = {"status": status} if status else None
        code, data = self._request("/api/v1/approvals", params=params)
        return data if code == 200 and isinstance(data, list) else []

    def grant_approval(self, request_id: str, reason: str | None = None) -> dict[str, Any]:
        """Grant an Action Firewall approval request."""
        payload = {"reason": reason or "Approved via CLI"}
        code, data = self._request(
            f"/api/v1/approvals/{request_id}/grant", method="POST", data=payload
        )
        return data if code == 200 else {"error": data.get("detail") or "Failed to grant approval"}

    def deny_approval(self, request_id: str, reason: str | None = None) -> dict[str, Any]:
        """Deny an Action Firewall approval request."""
        payload = {"reason": reason or "Denied via CLI"}
        code, data = self._request(
            f"/api/v1/approvals/{request_id}/deny", method="POST", data=payload
        )
        return data if code == 200 else {"error": data.get("detail") or "Failed to deny approval"}

    def list_workers(self) -> list[dict[str, Any]]:
        """List connected execution workers."""
        code, data = self._request("/api/v1/workers")
        return data if code == 200 and isinstance(data, list) else []

    # -------------------------------------------------------------------------
    # Collaboration & Governance APIs (Phase 17)
    # -------------------------------------------------------------------------

    def create_workspace(
        self,
        name: str,
        tenant_id: str = "default_tenant",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a collaborative workspace."""
        payload = {"name": name, "tenant_id": tenant_id, "metadata": metadata or {}}
        code, data = self._request("/api/v1/collaboration/workspaces", method="POST", data=payload)
        return (
            data
            if code in (200, 201)
            else {"error": data.get("detail") or "Failed to create workspace"}
        )

    def list_workspaces(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """List active collaborative workspaces."""
        code, data = self._request("/api/v1/collaboration/workspaces")
        return data if code == 200 and isinstance(data, list) else []

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        """Fetch workspace details."""
        code, data = self._request(f"/api/v1/collaboration/workspaces/{workspace_id}")
        return data if code == 200 else None

    def acquire_lease(
        self,
        workspace_id: str,
        identity: str,
        role: str = "OWNER",
        force: bool = False,
        duration_seconds: float = 300.0,
    ) -> dict[str, Any]:
        """Acquire or preempt a turn lease for a workspace."""
        payload = {
            "identity": identity,
            "role": role,
            "force": force,
            "duration_seconds": duration_seconds,
        }
        code, data = self._request(
            f"/api/v1/collaboration/workspaces/{workspace_id}/leases",
            method="POST",
            data=payload,
        )
        return (
            data
            if code in (200, 201)
            else {"error": data.get("detail") or "Failed to acquire turn lease"}
        )

    def pause_steering(
        self,
        workspace_id: str,
        reason: str,
        operator_id: str = "operator",
    ) -> dict[str, Any]:
        """Pause a workspace for active human steering."""
        payload = {
            "workspace_id": workspace_id,
            "reason": reason,
            "operator_id": operator_id,
        }
        code, data = self._request(
            "/api/v1/collaboration/steering/pause", method="POST", data=payload
        )
        return (
            data
            if code in (200, 201)
            else {"error": data.get("detail") or "Failed to pause for steering"}
        )

    def resume_steering(
        self,
        workspace_id: str,
        modified_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resume execution of a steered workspace."""
        payload = {
            "workspace_id": workspace_id,
            "modified_parameters": modified_parameters or {},
        }
        code, data = self._request(
            "/api/v1/collaboration/steering/resume", method="POST", data=payload
        )
        return (
            data
            if code in (200, 201)
            else {"error": data.get("detail") or "Failed to resume steering"}
        )

    def get_compliance_bundle(
        self,
        workspace_id: str,
        frameworks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Retrieve signed compliance bundle for a workspace."""
        code, data = self._request(f"/api/v1/collaboration/compliance/bundle/{workspace_id}")
        return (
            data
            if code == 200
            else {"error": data.get("detail") or "Failed to retrieve compliance bundle"}
        )
