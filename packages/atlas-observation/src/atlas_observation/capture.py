"""Observation capture engine generating standardized Observation contracts."""

import base64
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_core.contracts.observation import Observation
from playwright.async_api import Page

from atlas_observation.accessibility import extract_accessibility_tree
from atlas_observation.dom import extract_dom_snapshot, extract_interactive_elements


async def capture_screenshot(
    page: Page,
    full_page: bool = False,
    format: str = "png",
) -> bytes:
    """Capture raw viewport or full-page screenshot bytes."""
    return await page.screenshot(full_page=full_page, type=format)


async def capture_observation(
    page: Page,
    task_id: str,
    session_id: str,
    include_screenshot: bool = True,
    full_page: bool = False,
    include_interactive_elements: bool = True,
    save_dir: Path | str | None = None,
) -> Observation:
    """Capture a comprehensive environment observation of the active browser page."""
    now = datetime.now(UTC)
    obs_id = f"obs_{uuid.uuid4().hex[:12]}"

    url = page.url
    title = await page.title()

    # Capture DOM and accessibility snapshots
    dom = await extract_dom_snapshot(page)
    a11y = await extract_accessibility_tree(page)

    metadata: dict[str, Any] = {
        "url": url,
        "title": title,
    }

    screenshot_ref: str | None = None
    if include_screenshot:
        try:
            raw_bytes = await capture_screenshot(page, full_page=full_page)
            if save_dir:
                dir_path = Path(save_dir).resolve()
                dir_path.mkdir(parents=True, exist_ok=True)
                file_path = dir_path / f"{obs_id}.png"
                file_path.write_bytes(raw_bytes)
                metadata["screenshot_file"] = str(file_path)
            screenshot_ref = f"data:image/png;base64,{base64.b64encode(raw_bytes).decode('ascii')}"
        except Exception:
            screenshot_ref = None

    # Focused element check
    focused_selector: str | None = None
    try:
        focused_selector = await page.evaluate(
            "() => document.activeElement ? (document.activeElement.tagName.toLowerCase() + (document.activeElement.id ? '#' + document.activeElement.id : '')) : null"
        )
    except Exception:
        focused_selector = None

    if include_interactive_elements:
        metadata["interactive_elements"] = await extract_interactive_elements(page)

    return Observation(
        observation_id=obs_id,
        task_id=task_id,
        session_id=session_id,
        timestamp=now,
        screenshot_ref=screenshot_ref,
        dom_snapshot=dom,
        accessibility_tree=a11y,
        focused_element=focused_selector,
        window_title=title,
        metadata=metadata,
        schema_version="1.0",
    )
