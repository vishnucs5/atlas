"""Matcher implementations for deterministic post-condition verification."""

import re
from pathlib import Path
from typing import Any

from playwright.async_api import Page


async def match_element_visible(
    page: Page, target: str, timeout_ms: int = 5000
) -> tuple[bool, Any, str | None]:
    """Verify that an element identified by selector, text, or role is visible."""
    try:
        # Check text locator or css selector
        if target.startswith("text=") or target.startswith("role="):
            locator = page.locator(target)
        else:
            locator = page.locator(target).first

        await locator.wait_for(state="visible", timeout=timeout_ms)
        return True, "visible", None
    except Exception as exc:
        return False, "not visible or timed out", str(exc)


async def match_element_hidden(
    page: Page, target: str, timeout_ms: int = 5000
) -> tuple[bool, Any, str | None]:
    """Verify that an element is detached or hidden."""
    try:
        locator = page.locator(target).first
        await locator.wait_for(state="hidden", timeout=timeout_ms)
        return True, "hidden", None
    except Exception as exc:
        return False, "still visible or timed out", str(exc)


async def match_text_present(
    page: Page, target_text: str, timeout_ms: int = 5000
) -> tuple[bool, Any, str | None]:
    """Verify that expected text appears in the document body."""
    try:
        locator = page.locator(f"text={target_text}").first
        await locator.wait_for(state="visible", timeout=timeout_ms)
        return True, target_text, None
    except Exception as exc:
        # Fallback check raw page content
        try:
            content = await page.content()
            if target_text in content:
                return True, target_text, None
        except Exception:
            pass
        return False, "text not found", str(exc)


async def match_url(page: Page, expected_url_or_pattern: str) -> tuple[bool, Any, str | None]:
    """Verify that the current URL matches an exact string or regular expression."""
    current_url = page.url
    if current_url == expected_url_or_pattern:
        return True, current_url, None

    try:
        if re.search(expected_url_or_pattern, current_url):
            return True, current_url, None
    except re.error as exc:
        return False, current_url, f"Invalid regex pattern '{expected_url_or_pattern}': {exc}"

    return False, current_url, f"Expected '{expected_url_or_pattern}' but got '{current_url}'"


def match_file_downloaded(
    download_dir: Path | str, filename_or_prefix: str
) -> tuple[bool, Any, str | None]:
    """Verify that a downloaded file exists on disk and is non-empty."""
    path = Path(download_dir)
    if not path.exists():
        return False, None, f"Download directory does not exist: {download_dir}"

    target_file = path / filename_or_prefix
    if target_file.is_file():
        size = target_file.stat().st_size
        if size > 0:
            return True, {"path": str(target_file), "size": size}, None
        return False, {"path": str(target_file), "size": 0}, "File exists but is empty (0 bytes)"

    # Check for prefix or pattern match in download directory
    for item in path.iterdir():
        if item.is_file() and (
            item.name.startswith(filename_or_prefix) or filename_or_prefix in item.name
        ):
            size = item.stat().st_size
            if size > 0:
                return True, {"path": str(item), "size": size}, None

    return False, None, f"No matching file found for '{filename_or_prefix}' in {download_dir}"


async def match_value_equals(
    page: Page, target: str, expected_value: Any
) -> tuple[bool, Any, str | None]:
    """Verify input or element value equals expected value."""
    try:
        locator = page.locator(target).first
        actual_val = await locator.input_value()
        if str(actual_val) == str(expected_value):
            return True, actual_val, None
        return False, actual_val, f"Value mismatch: expected '{expected_value}', got '{actual_val}'"
    except Exception as exc:
        return False, None, str(exc)
