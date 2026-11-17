"""Configuration manager for ATLAS CLI."""

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "api_url": "http://127.0.0.1:8000",
    "api_key": "admin-key",
    "default_model": "atlas:hermetic-default",
    "timeout_seconds": 30.0,
    "output_format": "text",
    "default_mode": "minimal",
    "auto_approve_safe": False,
    "theme": "dark",
}


class ConfigManager:
    """Manages reading and writing persistent CLI configuration."""

    def __init__(self, config_dir: Path | None = None) -> None:
        if config_dir is not None:
            self.config_dir = config_dir
        else:
            atlas_home = os.environ.get("ATLAS_HOME")
            if atlas_home:
                self.config_dir = Path(atlas_home) / ".atlas"
            elif Path(".atlas").exists():
                self.config_dir = Path(".atlas")
            else:
                self.config_dir = Path.home() / ".atlas"

        self.config_file = self.config_dir / "config.json"
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        """Ensure config directory and file exist with defaults."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_file.exists():
            self._write(DEFAULT_CONFIG)

    def _read(self) -> dict[str, Any]:
        """Read configuration file from disk."""
        try:
            with open(self.config_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return dict(DEFAULT_CONFIG)

    def _write(self, data: dict[str, Any]) -> None:
        """Write configuration file to disk."""
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value by key, falling back to environment variable or default."""
        env_key = f"ATLAS_{key.upper()}"
        if env_key in os.environ:
            return os.environ[env_key]
        cfg = self._read()
        return cfg.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set config key value."""
        cfg = self._read()
        cfg[key] = value
        self._write(cfg)

    def list_all(self) -> dict[str, Any]:
        """Return all config key-value pairs."""
        return self._read()

    def reset(self) -> None:
        """Reset configuration to defaults."""
        self._write(DEFAULT_CONFIG)
