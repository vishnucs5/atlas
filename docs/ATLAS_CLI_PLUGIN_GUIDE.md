# ATLAS CLI Plugin Developer Guide

## 1. Overview

ATLAS CLI plugins allow developers to package new tools, workflows, or integrations into distributable, signed archives. This guide walks through authoring, testing, and distributing a custom plugin.

---

## 2. Anatomy of a Plugin Package

A plugin consists of a directory or tarball containing:

```
my-atlas-plugin/
├── manifest.json       # Structured package manifest
├── main.py             # Python entrypoint and tool implementations
└── README.md           # Documentation
```

### `manifest.json` Specification

```json
{
  "package_id": "custom-linter-pack",
  "package_type": "plugin",
  "name": "Custom Linter Integration",
  "version": "1.0.0",
  "description": "Integrates specialized organizational linters into ATLAS CLI.",
  "publisher": {
    "publisher_id": "org_engineering",
    "name": "Engineering Tools Team",
    "email": "devtools@company.com",
    "is_trusted": true
  },
  "permissions": [
    {
      "scope": "filesystem",
      "access": "read"
    }
  ]
}
```

---

## 3. Implementing the Plugin Entrypoint

In `main.py`, define the tool registration hook:

```python
"""Entrypoint for custom-linter-pack."""

from typing import Any


def run_custom_linter(arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute organization-specific static checks."""
    target_file = arguments.get("file_path")
    # Execute checks safely
    return {"status": "success", "violations": []}


def register_tools(mcp_manager) -> None:
    """Called by ATLAS CLI upon plugin activation."""
    mcp_manager.register_tool(
        tool_name="custom_linter.check",
        description="Run custom company linter on a source file",
        handler=run_custom_linter,
    )
```

---

## 4. Packaging and SHA-256 Checksums

Build the plugin archive:

```bash
tar -czvf custom-linter-pack-1.0.0.tar.gz -C my-atlas-plugin .
sha256sum custom-linter-pack-1.0.0.tar.gz
```

---

## 5. Installing the Plugin

Install the packaged archive locally using ATLAS CLI:

```bash
atlas plugins install custom-linter-pack-1.0.0.tar.gz
```

Verify the plugin state:
```bash
atlas plugins list
```
Output:
```text
[ATLAS WORKFLOW & SKILL PLUGINS]
Plugin Identifier     Version  Publisher       Status     
--------------------- -------- --------------- ----------- 
custom-linter-pack    1.0.0    org_engineering [INSTALLED]
```
