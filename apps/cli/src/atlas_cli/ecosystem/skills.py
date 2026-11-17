"""Skill ecosystem management, schema validation, prompt safety, and execution gating."""

import re
import threading
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from atlas_skills.models import (
    SkillCapability,
    SkillManifest,
    SkillParameter,
    SkillResult,
)
from pydantic import BaseModel, ConfigDict

INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b"),
    re.compile(r"(?i)\boverride\s+(?:system\s+)?policy\b"),
    re.compile(r"(?i)\bbypass\s+action\s+firewall\b"),
    re.compile(r"(?i)\bgrant\s+root\s+privileges\b"),
]


class SkillTrustStatus(StrEnum):
    """Trust classification for registered skills."""

    VERIFIED = "VERIFIED"
    UNVALIDATED = "UNVALIDATED"
    REJECTED = "REJECTED"


class SkillValidationError(Exception):
    """Raised when skill instructions contain security threats or invalid interfaces."""


SkillSecurityError = SkillValidationError
SkillExecutionResult = SkillResult


class RegisteredSkill(BaseModel):
    """In-memory registered skill with validation state and instruction safety markers."""

    model_config = ConfigDict(validate_assignment=True)

    manifest: SkillManifest
    instructions: str
    trust_status: SkillTrustStatus = SkillTrustStatus.UNVALIDATED
    is_validated: bool = False
    validation_error: str | None = None

    @property
    def skill_id(self) -> str:
        return self.manifest.skill_id

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def category(self) -> str:
        return self.manifest.capabilities[0] if self.manifest.capabilities else "general"

    @property
    def declared_permissions(self) -> list[str]:
        return [p.value if hasattr(p, "value") else str(p) for p in self.manifest.permissions]


class SkillManager:
    """Manages skill discovery, adversarial prompt validation, and policy-governed execution."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.skills: dict[str, RegisteredSkill] = {}
        self._executors: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self._load_builtins()

    def _load_builtins(self) -> None:
        """Register the 7 standard engineering built-in skills."""
        builtins = [
            SkillManifest(
                skill_id="skill_coding_workflow",
                name="Coding Workflow",
                version="1.0.0",
                description="Decompose, implement, and patch code modules.",
                capabilities=[SkillCapability.CODE],
                inputs={"objective": SkillParameter(name="objective", description="Target task")},
                outputs={"code": SkillParameter(name="code", description="Implemented patch")},
            ),
            SkillManifest(
                skill_id="skill_debugging_workflow",
                name="Debugging Workflow",
                version="1.0.0",
                description="Root-cause diagnosis and reproduction test fixtures.",
                capabilities=[SkillCapability.CODE],
                inputs={
                    "error_message": SkillParameter(name="error_message", description="Error log")
                },
                outputs={"fix": SkillParameter(name="fix", description="Bugfix")},
            ),
            SkillManifest(
                skill_id="skill_testing_workflow",
                name="Testing Workflow",
                version="1.0.0",
                description="Automated test discovery, execution, and reporting.",
                capabilities=[SkillCapability.QUALITY_ASSURANCE],
                inputs={
                    "test_target": SkillParameter(name="test_target", description="Path to test")
                },
                outputs={"summary": SkillParameter(name="summary", description="Pass/fail counts")},
            ),
            SkillManifest(
                skill_id="skill_security_analysis",
                name="Security Analysis",
                version="1.0.0",
                description="Secret detection and Action Firewall compliance audit.",
                capabilities=[SkillCapability.SECURITY_AUDIT],
                inputs={"files": SkillParameter(name="files", description="List of files")},
                outputs={
                    "findings": SkillParameter(name="findings", description="Security issues")
                },
            ),
            SkillManifest(
                skill_id="skill_documentation_workflow",
                name="Documentation Workflow",
                version="1.0.0",
                description="Markdown architecture and user manual authoring.",
                capabilities=[SkillCapability.TEXT_PROCESSING],
                inputs={"topic": SkillParameter(name="topic", description="Target module")},
                outputs={"markdown": SkillParameter(name="markdown", description="Documentation")},
            ),
            SkillManifest(
                skill_id="skill_repo_analysis",
                name="Repository Analysis",
                version="1.0.0",
                description="Codebase topology and dependency graph inspection.",
                capabilities=[SkillCapability.RESEARCH],
                inputs={"root": SkillParameter(name="root", description="Repo root")},
                outputs={"graph": SkillParameter(name="graph", description="Dependencies")},
            ),
            SkillManifest(
                skill_id="skill_infra_operations",
                name="Infrastructure Operations",
                version="1.0.0",
                description="Containerization, CI matrix, and environment tuning.",
                capabilities=[SkillCapability.CODE],
                inputs={"target": SkillParameter(name="target", description="Infra target")},
                outputs={"config": SkillParameter(name="config", description="Configuration")},
            ),
        ]

        for m in builtins:
            self.register_skill(
                manifest=m,
                instructions=f"Standard built-in instruction for {m.name}.",
                auto_validate=True,
            )

    def get_skill(self, skill_id: str) -> RegisteredSkill | None:
        """Retrieve a registered skill by identifier."""
        with self._lock:
            return self.skills.get(skill_id)

    def register_custom_skill(
        self,
        skill_id: str,
        name: str,
        instructions: str,
        capabilities: list[str] | None = None,
        inputs: dict[str, Any] | None = None,
        executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> RegisteredSkill:
        """Register a user-defined skill with adversarial instruction pre-screening."""
        for pat in INJECTION_PATTERNS:
            if pat.search(instructions):
                raise SkillValidationError(
                    f"Adversarial instruction pattern detected: '{pat.pattern}'"
                )

        parsed_inputs = {}
        if inputs:
            for k, v in inputs.items():
                if isinstance(v, dict):
                    parsed_inputs[k] = SkillParameter(
                        name=k,
                        description=v.get("description", ""),
                        required=v.get("required", False),
                    )
                else:
                    parsed_inputs[k] = SkillParameter(name=k, description="")

        manifest = SkillManifest(
            skill_id=skill_id,
            name=name,
            version="1.0.0",
            description="",
            capabilities=[SkillCapability.CODE],
            inputs=parsed_inputs,
        )
        return self.register_skill(
            manifest=manifest,
            instructions=instructions,
            auto_validate=True,
            executor=executor,
        )

    def register_skill(
        self,
        manifest: SkillManifest,
        instructions: str,
        auto_validate: bool = False,
        executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> RegisteredSkill:
        """Register a new skill with untrusted instruction tagging until verified."""
        with self._lock:
            skill = RegisteredSkill(
                manifest=manifest,
                instructions=instructions,
                trust_status=SkillTrustStatus.UNVALIDATED,
                is_validated=False,
            )
            self.skills[manifest.skill_id] = skill
            if executor:
                self._executors[manifest.skill_id] = executor

            if auto_validate:
                self.validate_skill(manifest.skill_id)

            return skill

    def validate_skill(self, skill_id: str) -> bool:
        """Validate skill instructions against prompt injection and policy override attempts."""
        with self._lock:
            skill = self.skills.get(skill_id)
            if not skill:
                msg = f"Skill '{skill_id}' not found."
                raise KeyError(msg)

            # Adversarial Prompt Scan
            for pat in INJECTION_PATTERNS:
                if pat.search(skill.instructions):
                    skill.trust_status = SkillTrustStatus.REJECTED
                    skill.is_validated = False
                    skill.validation_error = (
                        f"Adversarial instruction pattern detected: '{pat.pattern}'"
                    )
                    raise SkillValidationError(skill.validation_error)

            skill.trust_status = SkillTrustStatus.VERIFIED
            skill.is_validated = True
            skill.validation_error = None
            return True

    def execute_skill(
        self,
        skill_id: str,
        inputs: dict[str, Any],
    ) -> SkillResult:
        """Execute a validated skill."""
        with self._lock:
            skill = self.skills.get(skill_id)
            if not skill:
                return SkillResult(success=False, error=f"Skill '{skill_id}' not registered.")

            if not skill.is_validated:
                return SkillResult(
                    success=False,
                    error=f"Skill '{skill_id}' is UNVALIDATED. Must pass validation before execution.",
                )

            # Input schema verification
            for req_key, param in skill.manifest.inputs.items():
                if param.required and req_key not in inputs:
                    return SkillResult(
                        success=False,
                        error=f"Missing required parameter '{req_key}' for skill '{skill_id}'.",
                    )

            t0 = time.monotonic()
            try:
                executor = self._executors.get(skill_id)
                output = (
                    executor(inputs)
                    if executor
                    else {"status": "success", "result": f"Executed {skill.manifest.name}"}
                )
                elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
                return SkillResult(
                    success=True,
                    output=output,
                    execution_time_ms=elapsed_ms,
                    logs=[f"Successfully executed {skill.manifest.name}"],
                )
            except Exception as exc:
                elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
                return SkillResult(
                    success=False,
                    error=str(exc),
                    execution_time_ms=elapsed_ms,
                )

    def list_skills(self) -> list[RegisteredSkill]:
        """Return all registered skills."""
        with self._lock:
            return list(self.skills.values())
