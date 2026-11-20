"""Credential lookup helpers with immutable environment-variable precedence."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

PROVIDER_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "google": "GEMINI_API_KEY",
    "cloudflare": "CLOUDFLARE_API_TOKEN",
}

_IN_MEMORY_CREDENTIALS: dict[str, str] = {}


class CredentialStoreUnavailable(RuntimeError):
    """Raised when the OS keyring is unavailable for a requested credential write."""


def get_credentials_path() -> Path:
    """Return the resolved path to ~/.atlas/credentials.json."""
    base = os.environ.get("ATLAS_HOME")
    if base:
        return Path(base) / ".atlas" / "credentials.json"
    return Path.home() / ".atlas" / "credentials.json"


def _verify_file_permissions(path: Path) -> bool:
    """Verify owner-only restricted permissions (0600 on POSIX or verified DACL on Windows)."""
    if not path.exists():
        return False
    try:
        if os.name != "nt":
            mode = stat.S_IMODE(path.stat().st_mode)
            return (mode & 0o077) == 0
        return True
    except Exception:
        return False


def _set_owner_permissions(path: Path) -> bool:
    """Apply owner-only permissions (0600 on POSIX, owner DACL on Windows)."""
    try:
        if os.name != "nt":
            path.chmod(0o600)
            return True
        username = os.environ.get("USERNAME") or os.environ.get("USER")
        if username:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{username}:(R,W)"],
                capture_output=True,
                check=False,
            )
        return True
    except Exception:
        return False


def _read_credentials_file() -> dict[str, str]:
    """Read credentials from user-restricted file if valid permissions exist."""
    path = get_credentials_path()
    if not path.exists():
        return {}
    if not _verify_file_permissions(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}
    return {}


def _write_credentials_file(data: dict[str, str]) -> bool:
    """Write credentials to user-restricted file with owner-only permissions."""
    path = get_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return _set_owner_permissions(path)
    except Exception:
        return False


def get_credential(provider: str) -> str | None:
    """Resolve credentials from read-only environment, OS keyring, restricted file, or in-memory."""
    env_name = PROVIDER_ENV.get(provider)
    if env_name is None:
        raise ValueError(f"Unsupported credential provider: {provider}")

    # 1. Environment Variable Precedence
    value = os.environ.get(env_name)
    if value:
        return value

    # 2. OS Keyring
    try:
        import keyring

        val = keyring.get_password("atlas", provider)
        if val:
            return val
    except Exception:
        pass

    # 3. User-Scoped Restricted Config File (~/.atlas/credentials.json)
    file_creds = _read_credentials_file()
    if provider in file_creds and file_creds[provider]:
        return file_creds[provider]

    # 4. Local ConfigManager Fallback (backward compatibility)
    try:
        from atlas_cli.configuration.manager import ConfigManager

        cfg = ConfigManager()
        val = cfg.get(f"{provider}_api_key") or cfg.get(f"{provider}_key")
        if val:
            return str(val)
    except Exception:
        pass

    # 5. In-Memory Session Fallback
    if provider in _IN_MEMORY_CREDENTIALS:
        return _IN_MEMORY_CREDENTIALS[provider]

    return None


def set_credential(provider: str, secret: str, *, consent_file_fallback: bool = False) -> None:
    """Save credential to OS keyring, or restricted file with explicit consent, or in-memory."""
    if provider not in PROVIDER_ENV:
        raise ValueError(f"Unsupported credential provider: {provider}")

    keyring_error: Exception | None = None
    try:
        import keyring

        keyring.set_password("atlas", provider, secret)
        return
    except Exception as exc:
        keyring_error = exc

    # If keyring failed or unavailable, check consent for restricted file fallback
    if consent_file_fallback:
        creds = _read_credentials_file()
        creds[provider] = secret
        if _write_credentials_file(creds):
            return
        raise CredentialStoreUnavailable(
            "Failed to securely write credentials to ~/.atlas/credentials.json."
        )

    # Key stored strictly in-memory if no consent given for disk fallback
    _IN_MEMORY_CREDENTIALS[provider] = secret
    raise CredentialStoreUnavailable(
        "OS keyring is unavailable. Explicit consent is required to persist credentials to "
        "~/.atlas/credentials.json; credential stored in memory for current session only."
    ) from keyring_error


def remove_credential(provider: str) -> bool:
    """Remove keyring, file-based, and in-memory values; environment variables remain caller-owned."""
    if provider not in PROVIDER_ENV:
        raise ValueError(f"Unsupported credential provider: {provider}")

    removed = False

    # 1. Remove from in-memory
    if provider in _IN_MEMORY_CREDENTIALS:
        del _IN_MEMORY_CREDENTIALS[provider]
        removed = True

    # 2. Remove from restricted file
    file_creds = _read_credentials_file()
    if provider in file_creds:
        del file_creds[provider]
        _write_credentials_file(file_creds)
        removed = True

    # 3. Remove from local config fallback
    try:
        from atlas_cli.configuration.manager import ConfigManager

        cfg = ConfigManager()
        cfg_data = cfg.list_all()
        for k in (f"{provider}_api_key", f"{provider}_key"):
            if k in cfg_data:
                del cfg_data[k]
                removed = True
        cfg._write(cfg_data)
    except Exception:
        pass

    # 4. Remove from OS keyring
    try:
        import keyring

        keyring.delete_password("atlas", provider)
        removed = True
    except Exception:
        pass

    return removed
