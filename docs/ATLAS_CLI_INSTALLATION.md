# ATLAS CLI Installation Guide

## 1. System Requirements

Before installing ATLAS CLI, verify that your environment meets the minimum prerequisites:

- **Operating System**:
  - Windows 11 / Windows 10 (Build 19041+)
  - Linux (Ubuntu 22.04+, Debian 12+, Fedora 38+, Arch Linux)
  - macOS (macOS 13 Ventura, macOS 14 Sonoma, macOS 15 Sequoia on Apple Silicon & Intel)
- **Python**: Version 3.11 or 3.12 (64-bit required)
- **Disk Space**: 200 MB for core installation; 2 GB recommended for Playwright browser binaries
- **Memory**: Minimum 4 GB RAM; 8 GB+ recommended for large repository indexing and multi-agent coordination

---

## 2. Installation Methods

### Method A: Install via `uv` (Recommended)

[`uv`](https://github.com/astral-sh/uv) provides the fastest, isolated tool installation experience:

```bash
# Install atlas-cli into an isolated tool environment
uv tool install atlas-cli

# Verify installation
atlas --version
atlas doctor
```

To update in the future:
```bash
uv tool upgrade atlas-cli
```

---

### Method B: Install via `pip`

You can install ATLAS CLI directly using standard Python packaging:

```bash
# Recommended: inside an isolated virtual environment
python -m venv ~/.atlas-env
source ~/.atlas-env/bin/activate  # On Windows: ~/.atlas-env\Scripts\activate

pip install --upgrade pip
pip install atlas-cli

atlas --version
```

---

### Method C: Local Wheel Installation (Air-Gapped / Offline Environments)

For air-gapped workstations or enterprise testing:

```bash
# From release distribution artifacts
pip install dist/atlas_cli-0.16.8-py3-none-any.whl

# Verify offline readiness
atlas edition
```

---

## 3. Post-Installation Verification

Run the built-in system diagnostics suite:

```bash
atlas doctor
```

Expected diagnostic output:
```text
ATLAS Environment Diagnostics
=============================
  Python: 3.11.9 (>= 3.11 required) [OK]
  Platform: win32 (Windows-10-10.0.26200-SP0) [OK]
  Windows Long Paths: Enabled [OK]
  SQLite: 3.45.1 (WAL mode supported) [OK]
  Playwright Chromium: Available [OK]
  Workspace: Initialized (.atlas) [OK]
=============================
System status: HEALTHY
```

---

## 4. Uninstallation and Cleanup

ATLAS respects user data sovereignty. Removing the binary does **never** delete your repository state, configuration, or session logs unless explicitly deleted:

```bash
# If installed via uv
uv tool uninstall atlas-cli

# If installed via pip
pip uninstall atlas-cli

# Optional: To purge local workspace state and session logs
rm -rf .atlas/
```

---

## 5. Platform Support Matrix & Status

- **Windows 11**: Locally verified pass (PowerShell, Windows Terminal, Python 3.11.9).
- **Ubuntu Linux**: CI configured in `.github/workflows/ci.yml`; pending execution on remote GitHub Actions runners.
- **macOS**: CI configured in `.github/workflows/ci.yml`; pending execution on remote GitHub Actions runners.

