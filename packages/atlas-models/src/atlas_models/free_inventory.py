"""Short-lived cache for model IDs discovered from zero-cost provider inventory."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

CACHE_FILENAME = "openrouter_free_inventory.json"
CACHE_MAX_AGE = timedelta(hours=1)
CONFIG_FILENAME = "config.json"
DEFAULT_MODEL = "openrouter/free"


def atlas_config_dir() -> Path:
    atlas_home = os.environ.get("ATLAS_HOME")
    if atlas_home:
        return Path(atlas_home) / ".atlas"
    if Path(".atlas").exists():
        return Path(".atlas")
    return Path.home() / ".atlas"


def load_selected_model(config_dir: Path | None = None) -> str:
    """Read the user-selected exact model ID without importing the CLI package."""
    path = (config_dir or atlas_config_dir()) / CONFIG_FILENAME
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DEFAULT_MODEL
    try:
        document: dict[str, Any] = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("ATLAS model configuration is malformed.") from exc
    selected = document.get("default_model", DEFAULT_MODEL)
    if not isinstance(selected, str) or not selected.strip():
        raise ValueError("ATLAS default_model must be a non-empty string.")
    return selected


def load_cached_free_ids(
    config_dir: Path | None = None, now: datetime | None = None
) -> tuple[str, ...]:
    """Return cached exact OpenRouter :free IDs only while the inventory is fresh."""
    path = (config_dir or atlas_config_dir()) / CACHE_FILENAME
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    try:
        document: dict[str, Any] = json.loads(content)
        refreshed = datetime.fromisoformat(document["refreshed_at"])
        ids = document["model_ids"]
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("OpenRouter free inventory cache is malformed.") from exc
    if not isinstance(ids, list):
        raise ValueError("OpenRouter free inventory model_ids must be a list.")
    if refreshed.tzinfo is None:
        raise ValueError("OpenRouter free inventory timestamp must include a timezone.")
    current = now or datetime.now(UTC)
    if current - refreshed > CACHE_MAX_AGE or refreshed > current:
        return ()
    return tuple(sorted({item for item in ids if isinstance(item, str) and item.endswith(":free")}))


def save_cached_free_ids(model_ids: list[str], config_dir: Path | None = None) -> Path:
    """Atomically save exact `:free` model IDs with an auditable refresh timestamp."""
    allowed = sorted({item for item in model_ids if item.endswith(":free")})
    directory = config_dir or atlas_config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CACHE_FILENAME
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {"refreshed_at": datetime.now(UTC).isoformat(), "model_ids": allowed},
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
