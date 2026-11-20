"""Credential lookup helpers with immutable environment-variable precedence."""

from __future__ import annotations

import os

PROVIDER_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "google": "GEMINI_API_KEY",
    "cloudflare": "CLOUDFLARE_API_TOKEN",
}


class CredentialStoreUnavailable(RuntimeError):
    """Raised when the OS keyring is unavailable for a requested credential write."""


def get_credential(provider: str) -> str | None:
    """Resolve credentials from the read-only environment, then OS keyring, then local config."""
    env_name = PROVIDER_ENV.get(provider)
    if env_name is None:
        raise ValueError(f"Unsupported credential provider: {provider}")
    value = os.environ.get(env_name)
    if value:
        return value
    try:
        import keyring
    except ImportError:
        pass
    else:
        try:
            val = keyring.get_password("atlas", provider)
            if val:
                return val
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreUnavailable("The OS keyring could not be read.") from exc

    try:
        from atlas_cli.configuration.manager import ConfigManager

        cfg = ConfigManager()
        val = cfg.get(f"{provider}_api_key") or cfg.get(f"{provider}_key")
        if val:
            return str(val)
    except Exception:
        pass

    return None


def set_credential(provider: str, secret: str) -> None:
    """Save a credential into the OS keyring and local config fallback."""
    if provider not in PROVIDER_ENV:
        raise ValueError(f"Unsupported credential provider: {provider}")

    # Save to config fallback
    try:
        from atlas_cli.configuration.manager import ConfigManager

        cfg = ConfigManager()
        cfg.set(f"{provider}_api_key", secret)
    except Exception:
        pass

    try:
        import keyring
    except ImportError as exc:
        raise CredentialStoreUnavailable(
            "OS keyring support is unavailable. Install the keyring package or set the provider environment variable."
        ) from exc
    try:
        keyring.set_password("atlas", provider, secret)
    except keyring.errors.KeyringError as exc:
        raise CredentialStoreUnavailable("The OS keyring could not store this credential.") from exc


def remove_credential(provider: str) -> bool:
    """Remove keyring and config values; environment variables remain caller-owned."""
    if provider not in PROVIDER_ENV:
        raise ValueError(f"Unsupported credential provider: {provider}")
    removed = False
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

    try:
        import keyring
    except ImportError:
        return removed
    try:
        keyring.delete_password("atlas", provider)
        removed = True
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.KeyringError as exc:
        raise CredentialStoreUnavailable(
            "The OS keyring could not remove this credential."
        ) from exc
    return removed
