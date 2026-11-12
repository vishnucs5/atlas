"""Browser configuration options for ATLAS."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class BrowserConfig(BaseModel):
    """Configuration options for Playwright Chromium driver."""

    model_config = ConfigDict(validate_assignment=True)

    headless: bool = True
    slow_mo_ms: int = 0
    viewport_width: int = 1280
    viewport_height: int = 800
    timeout_ms: int = 30000
    navigation_timeout_ms: int = 30000
    download_dir: Path | str | None = None
    artifacts_dir: Path | str | None = None
    user_agent: str | None = None
    accept_downloads: bool = True
    ignore_https_errors: bool = True
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
