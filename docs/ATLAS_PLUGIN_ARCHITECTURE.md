# ATLAS Plugin Architecture & Lifecycle Specification

## 1. Architectural Principles

ATLAS CLI plugins are packaged, signed extensions that add capabilities, tools, or workflow steps to the developer environment. The architecture is explicitly decoupled from core execution to ensure stability and security:

1. **Manifest-First Contract**: Plugins must provide a structured `PackageManifest` defining identifier, semver version, author, capabilities, and requested permission scopes.
2. **Cryptographic Integrity**: Every plugin bundle is validated against an authoritative SHA-256 checksum before unpacking or loading into memory.
3. **Publisher Trust**: In enterprise environments, plugins must be signed by verified publishers (`is_trusted: True`); unsigned or untrusted packages are rejected.
4. **Action Firewall Scoping**: Declared permission scopes (e.g. `FILESYSTEM`, `NETWORK`) are converted into firewall policies; requesting forbidden permissions (such as unrestricted root access) triggers an immediate security error.
5. **Auditable State Transitions**: All lifecycle events (install, enable, disable, upgrade, uninstall) are logged to an append-only audit trail.

---

## 2. Plugin Lifecycle State Machine

```
              ┌───────────────┐
              │  Uninstalled  │
              └───────┬───────┘
                      │ install_plugin()
                      ▼
              ┌───────────────┐
       ┌─────>│   INSTALLED   │<─────┐
       │      └───────┬───────┘      │
       │              │ enable_plugin()
       │              ▼              │
       │      ┌───────────────┐      │
       │      │    ENABLED    │      │
       │      └───────┬───────┘      │
       │              │ disable_plugin()
       │              ▼              │
       │      ┌───────────────┐      │
       └──────│   DISABLED    ├──────┘
              └───────┬───────┘
                      │ uninstall_plugin()
                      ▼
              ┌───────────────┐
              │  Uninstalled  │
              └───────────────┘
```

---

## 3. Package Manifest Schema

Plugins declare their dependencies and security constraints using the standard ATLAS marketplace schema:

```json
{
  "package_id": "atlas-browser-pack",
  "package_type": "plugin",
  "name": "ATLAS Browser Automation Pack",
  "version": "1.0.0",
  "description": "Playwright-based web interaction drivers for ATLAS CLI.",
  "publisher": {
    "publisher_id": "atlas_official",
    "name": "ATLAS Core Team",
    "email": "security@atlas.dev",
    "is_trusted": true
  },
  "permissions": [
    {
      "scope": "browser",
      "access": "read_write"
    },
    {
      "scope": "network",
      "access": "http_client"
    }
  ]
}
```

---

## 4. Integrity and Trust Verification

1. **Hash Verification**: `hashlib.sha256(archive_bytes).hexdigest() == expected_checksum`.
   If a mismatch occurs, the plugin state is recorded as `CORRUPTED` and a `PluginSecurityError` is raised.
2. **Permission Boundary Check**: Plugins declaring unauthorized system modifications or attempting privilege escalation are halted at the firewall gate.
3. **Dependency Resolution**: Version constraints are parsed using SemVer compatibility rules to prevent dependency collisions across active plugins.
