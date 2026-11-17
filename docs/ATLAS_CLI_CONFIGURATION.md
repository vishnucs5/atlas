# ATLAS CLI Configuration Specification

## 1. Configuration Precedence Hierarchy

ATLAS CLI loads configuration values using a deterministic 4-tier precedence hierarchy:

```
  1. Command-Line Arguments (Highest Precedence)
        │
  2. Environment Variables (e.g. ATLAS_DEFAULT_MODEL)
        │
  3. Local Project Configuration (.atlas/config.json)
        │
  4. Global System Defaults (Lowest Precedence)
```

Values defined at higher tiers strictly override lower tiers without mutating underlying configuration files.

---

## 2. Configuration File Format (`.atlas/config.json`)

The local configuration file resides in the root `.atlas/` directory:

```json
{
  "default_mode": "minimal",
  "active_profile": "python-dev",
  "model": {
    "provider": "hermetic",
    "name": "hermetic-default",
    "temperature": 0.2,
    "max_tokens": 4096
  },
  "execution": {
    "max_parallel_workers": 4,
    "sandbox_timeout_seconds": 300,
    "auto_verify_tests": true,
    "optimistic_concurrency": true
  },
  "security": {
    "require_human_approval_on_critical": true,
    "block_private_network_access": true,
    "redact_secrets": true
  }
}
```

---

## 3. Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `ATLAS_HOME` | Custom root path for `.atlas/` state storage | Current working directory |
| `ATLAS_EDITION` | Active product edition (`open-source` or `enterprise`) | `open-source` |
| `ATLAS_LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `ATLAS_FIREWALL_STRICT` | Force `DENY` decision on unclassified action types | `false` |
| `ATLAS_MAX_CONTEXT_TOKENS`| Hard ceiling on assembled context size | `8000` |

---

## 4. Configuration CLI Management

Manage configuration keys safely from the terminal:

```bash
# View all current configuration settings
atlas config

# Set a configuration value
atlas config default_mode tui

# Set active profile
atlas config active_profile typescript-dev
```
