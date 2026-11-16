"""Kubernetes Admission Validation Engine for ATLAS Custom Resources."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from atlas_operator.models import (
    AtlasAgentPool,
    AtlasCluster,
    AtlasDeployment,
    AtlasExecutionPolicy,
    AtlasWorkerPool,
)


class AdmissionResult:
    """Result of an admission review."""

    def __init__(
        self,
        allowed: bool,
        reason: str = "Admission allowed",
        violations: list[str] | None = None,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.violations = violations or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": {
                "message": self.reason,
                "details": {"violations": self.violations},
            },
        }

    def __repr__(self) -> str:
        return f"AdmissionResult(allowed={self.allowed}, reason='{self.reason}', violations={self.violations})"


class AtlasAdmissionValidator:
    """Validates ATLAS Custom Resources before persistence in Kubernetes."""

    @classmethod
    def validate_cluster(cls, manifest: dict[str, Any]) -> AdmissionResult:
        """Validate AtlasCluster resource manifest."""
        try:
            name = manifest.get("metadata", {}).get("name", "")
            spec = manifest.get("spec", {})
            AtlasCluster(name=name, spec=spec)
            return AdmissionResult(allowed=True, reason="AtlasCluster spec valid")
        except ValidationError as e:
            violations = [
                f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()
            ]
            return AdmissionResult(
                allowed=False,
                reason="AtlasCluster validation failed",
                violations=violations,
            )

    @classmethod
    def validate_worker_pool(cls, manifest: dict[str, Any]) -> AdmissionResult:
        """Validate AtlasWorkerPool resource manifest."""
        try:
            name = manifest.get("metadata", {}).get("name", "")
            namespace = manifest.get("metadata", {}).get("namespace", "default")
            spec = manifest.get("spec", {})
            AtlasWorkerPool(name=name, namespace=namespace, spec=spec)
            return AdmissionResult(allowed=True, reason="AtlasWorkerPool spec valid")
        except ValidationError as e:
            violations = [
                f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()
            ]
            return AdmissionResult(
                allowed=False,
                reason="AtlasWorkerPool validation failed",
                violations=violations,
            )

    @classmethod
    def validate_agent_pool(cls, manifest: dict[str, Any]) -> AdmissionResult:
        """Validate AtlasAgentPool resource manifest."""
        try:
            name = manifest.get("metadata", {}).get("name", "")
            namespace = manifest.get("metadata", {}).get("namespace", "default")
            spec = manifest.get("spec", {})
            AtlasAgentPool(name=name, namespace=namespace, spec=spec)
            return AdmissionResult(allowed=True, reason="AtlasAgentPool spec valid")
        except ValidationError as e:
            violations = [
                f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()
            ]
            return AdmissionResult(
                allowed=False,
                reason="AtlasAgentPool validation failed",
                violations=violations,
            )

    @classmethod
    def validate_execution_policy(cls, manifest: dict[str, Any]) -> AdmissionResult:
        """Validate AtlasExecutionPolicy resource manifest."""
        try:
            name = manifest.get("metadata", {}).get("name", "")
            namespace = manifest.get("metadata", {}).get("namespace", "default")
            spec = manifest.get("spec", {})
            AtlasExecutionPolicy(name=name, namespace=namespace, spec=spec)
            return AdmissionResult(allowed=True, reason="AtlasExecutionPolicy spec valid")
        except ValidationError as e:
            violations = [
                f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()
            ]
            return AdmissionResult(
                allowed=False,
                reason="AtlasExecutionPolicy validation failed",
                violations=violations,
            )

    @classmethod
    def validate_deployment(cls, manifest: dict[str, Any]) -> AdmissionResult:
        """Validate AtlasDeployment resource manifest."""
        try:
            name = manifest.get("metadata", {}).get("name", "")
            namespace = manifest.get("metadata", {}).get("namespace", "default")
            spec = manifest.get("spec", {})
            AtlasDeployment(name=name, namespace=namespace, spec=spec)
            return AdmissionResult(allowed=True, reason="AtlasDeployment spec valid")
        except ValidationError as e:
            violations = [
                f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()
            ]
            return AdmissionResult(
                allowed=False,
                reason="AtlasDeployment validation failed",
                violations=violations,
            )

    @classmethod
    def review(cls, manifest: dict[str, Any]) -> AdmissionResult:
        """Review any recognized ATLAS Kubernetes manifest."""
        kind = manifest.get("kind", "")
        if kind == "AtlasCluster":
            return cls.validate_cluster(manifest)
        elif kind == "AtlasWorkerPool":
            return cls.validate_worker_pool(manifest)
        elif kind == "AtlasAgentPool":
            return cls.validate_agent_pool(manifest)
        elif kind == "AtlasExecutionPolicy":
            return cls.validate_execution_policy(manifest)
        elif kind == "AtlasDeployment":
            return cls.validate_deployment(manifest)
        else:
            return AdmissionResult(allowed=False, reason=f"Unrecognized resource kind: '{kind}'")
