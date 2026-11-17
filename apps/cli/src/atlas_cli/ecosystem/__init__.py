"""ATLAS CLI Ecosystem & Extensibility Architecture.

Exposes MCP client integrations, plugin management, skill execution,
workspace profile configurations, enterprise connectivity, and remote federation.
"""

from atlas_cli.ecosystem.edition import (
    EditionFeatureMatrix,
    EditionTier,
    EnterpriseFeatureRequiredError,
    FeatureDefinition,
)
from atlas_cli.ecosystem.enterprise import (
    EnterpriseAuthError,
    EnterpriseClientAdapter,
    EnterprisePolicyError,
    EnterpriseSessionInfo,
)
from atlas_cli.ecosystem.mcp import (
    MCPClientManager,
    MCPExecutionError,
    MCPServerConfig,
    MCPToolResult,
    MCPToolSchema,
)
from atlas_cli.ecosystem.plugins import (
    InstalledPlugin,
    PluginAuditEvent,
    PluginDependencyError,
    PluginManager,
    PluginSecurityError,
)
from atlas_cli.ecosystem.profiles import (
    PrivilegeBoundaryViolationError,
    WorkspaceProfile,
    WorkspaceProfileManager,
)
from atlas_cli.ecosystem.remote import (
    RemoteNodeInfo,
    RemoteRuntimeClient,
    RemoteRuntimeConnectionError,
    RemoteSessionLease,
    RemoteStreamEvent,
)
from atlas_cli.ecosystem.skills import (
    RegisteredSkill,
    SkillExecutionResult,
    SkillManager,
    SkillSecurityError,
)

__all__ = [
    # MCP
    "MCPServerConfig",
    "MCPToolSchema",
    "MCPToolResult",
    "MCPExecutionError",
    "MCPClientManager",
    # Plugins
    "InstalledPlugin",
    "PluginAuditEvent",
    "PluginSecurityError",
    "PluginDependencyError",
    "PluginManager",
    # Skills
    "RegisteredSkill",
    "SkillExecutionResult",
    "SkillSecurityError",
    "SkillManager",
    # Profiles
    "WorkspaceProfile",
    "PrivilegeBoundaryViolationError",
    "WorkspaceProfileManager",
    # Enterprise
    "EnterpriseSessionInfo",
    "EnterpriseAuthError",
    "EnterprisePolicyError",
    "EnterpriseClientAdapter",
    # Remote
    "RemoteNodeInfo",
    "RemoteSessionLease",
    "RemoteStreamEvent",
    "RemoteRuntimeConnectionError",
    "RemoteRuntimeClient",
    # Edition
    "EditionTier",
    "EnterpriseFeatureRequiredError",
    "FeatureDefinition",
    "EditionFeatureMatrix",
]
