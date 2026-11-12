"""Secure download and upload manager for browser sessions."""

import hashlib
from pathlib import Path
from typing import Any

from playwright.async_api import Download, Page


class DownloadManager:
    """Monitors and intercepts file downloads into an isolated directory."""

    def __init__(self, download_dir: Path | str) -> None:
        self.download_dir = Path(download_dir).resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.downloaded_files: list[dict[str, Any]] = []

    def attach(self, page: Page) -> None:
        """Listen for download events on page."""
        page.on("download", self._on_download)

    async def _on_download(self, download: Download) -> None:
        """Handle incoming download event, safely saving inside download_dir."""
        suggested_filename = download.suggested_filename
        target_path = (self.download_dir / suggested_filename).resolve()

        # Prevent directory traversal attacks
        if not str(target_path).startswith(str(self.download_dir)):
            target_path = self.download_dir / Path(suggested_filename).name

        await download.save_as(target_path)

        # Calculate checksum and size
        size = target_path.stat().st_size
        sha256 = hashlib.sha256(target_path.read_bytes()).hexdigest()

        record = {
            "filename": target_path.name,
            "path": str(target_path),
            "size_bytes": size,
            "sha256": sha256,
            "url": download.url,
        }
        self.downloaded_files.append(record)

    def get_downloaded_files(self) -> list[dict[str, Any]]:
        """Return list of files downloaded in this session."""
        return list(self.downloaded_files)
