"""Action execution implementation for browser operations."""

import asyncio
from pathlib import Path
from typing import Any

from atlas_core.contracts.action import ComputerAction
from atlas_core.runtime.exceptions import (
    ActionExecutionError,
    DetachedElementError,
    ElementNotFoundError,
    NavigationTimeoutError,
)
from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from atlas_browser.locators import resolve_coordinates, resolve_locator


class BrowserActionExecutor:
    """Executes validated ComputerAction contracts in Playwright browser context."""

    def __init__(self, context: BrowserContext, download_dir: Path | str | None = None) -> None:
        self.context = context
        self.download_dir = Path(download_dir).resolve() if download_dir else None

    async def execute(
        self, action: ComputerAction, active_page: Page
    ) -> tuple[Any, dict[str, Any]]:
        """Dispatch action to handler based on action_type.

        Returns (output, evidence_dict).
        """
        action_type = action.action_type.lower()
        params = action.parameters
        target = action.target
        timeout_ms = action.timeout_ms

        if action_type in ("browser.navigate", "navigate", "browser.goto"):
            return await self._navigate(active_page, params, timeout_ms)

        elif action_type in ("browser.click", "click"):
            return await self._click(active_page, target, params, timeout_ms)

        elif action_type in ("browser.type", "type"):
            return await self._type(active_page, target, params, timeout_ms)

        elif action_type in ("browser.fill", "fill"):
            return await self._fill(active_page, target, params, timeout_ms)

        elif action_type in ("browser.select", "select"):
            return await self._select(active_page, target, params, timeout_ms)

        elif action_type in ("browser.scroll", "scroll"):
            return await self._scroll(active_page, target, params)

        elif action_type in ("browser.press_key", "press_key", "key_press"):
            return await self._press_key(active_page, target, params)

        elif action_type in ("browser.wait", "wait"):
            return await self._wait(active_page, target, params, timeout_ms)

        elif action_type in ("browser.upload", "upload"):
            return await self._upload(active_page, target, params, timeout_ms)

        elif action_type in ("browser.new_tab", "new_tab"):
            return await self._new_tab(params)

        elif action_type in ("browser.close_tab", "close_tab"):
            return await self._close_tab(active_page)

        else:
            raise ActionExecutionError(f"Unsupported browser action type: '{action.action_type}'")

    async def _navigate(
        self, page: Page, params: dict[str, Any], timeout_ms: int
    ) -> tuple[Any, dict[str, Any]]:
        url = params.get("url")
        if not url:
            raise ActionExecutionError("Action 'browser.navigate' requires 'url' parameter")

        wait_until = params.get("wait_until", "domcontentloaded")
        try:
            response = await page.goto(str(url), wait_until=wait_until, timeout=timeout_ms)
            status_code = response.status if response else 200
            return (
                {"url": page.url, "title": await page.title(), "status_code": status_code},
                {"target_url": url, "final_url": page.url, "status_code": status_code},
            )
        except PlaywrightTimeoutError as exc:
            raise NavigationTimeoutError(
                f"Navigation to '{url}' timed out after {timeout_ms}ms: {exc}"
            ) from exc
        except Exception as exc:
            raise ActionExecutionError(f"Navigation to '{url}' failed: {exc}") from exc

    async def _click(
        self,
        page: Page,
        target: Any | None,
        params: dict[str, Any],
        timeout_ms: int,
    ) -> tuple[Any, dict[str, Any]]:
        coords = resolve_coordinates(target, params)
        button = params.get("button", "left")
        click_count = params.get("click_count", 1)

        if coords:
            x, y = coords
            await page.mouse.click(x, y, button=button, click_count=click_count)
            return (
                {"clicked": "coordinates", "x": x, "y": y},
                {"coordinates": {"x": x, "y": y}},
            )

        if not target:
            raise ActionExecutionError(
                "Click action requires either target element specification or coordinates"
            )

        locator = resolve_locator(page, target)
        try:
            await locator.click(timeout=timeout_ms, button=button, click_count=click_count)
            return (
                {"clicked": "element", "target": target.model_dump()},
                {"target": target.model_dump()},
            )
        except PlaywrightTimeoutError as exc:
            raise ElementNotFoundError(
                f"Target element not found or not clickable: {target}"
            ) from exc
        except Exception as exc:
            if "detached" in str(exc).lower():
                raise DetachedElementError(
                    f"Element detached before click completed: {target}"
                ) from exc
            raise ActionExecutionError(f"Click failed: {exc}") from exc

    async def _type(
        self,
        page: Page,
        target: Any | None,
        params: dict[str, Any],
        timeout_ms: int,
    ) -> tuple[Any, dict[str, Any]]:
        text = params.get("text", "")
        delay_ms = params.get("delay_ms", 0)

        if target:
            locator = resolve_locator(page, target)
            try:
                await locator.press_sequentially(str(text), delay=delay_ms, timeout=timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise ElementNotFoundError(
                    f"Target element for typing not found: {target}"
                ) from exc
        else:
            await page.keyboard.type(str(text), delay=delay_ms)

        return (
            {"typed_length": len(str(text))},
            {"target": target.model_dump() if target else None},
        )

    async def _fill(
        self,
        page: Page,
        target: Any | None,
        params: dict[str, Any],
        timeout_ms: int,
    ) -> tuple[Any, dict[str, Any]]:
        if not target:
            raise ActionExecutionError("Fill action requires target specification")

        value = params.get("value", "")
        locator = resolve_locator(page, target)
        try:
            await locator.fill(str(value), timeout=timeout_ms)
            return (
                {"filled": True, "value_length": len(str(value))},
                {"target": target.model_dump()},
            )
        except PlaywrightTimeoutError as exc:
            raise ElementNotFoundError(f"Target element for fill not found: {target}") from exc

    async def _select(
        self,
        page: Page,
        target: Any | None,
        params: dict[str, Any],
        timeout_ms: int,
    ) -> tuple[Any, dict[str, Any]]:
        if not target:
            raise ActionExecutionError("Select action requires target specification")

        value = params.get("value")
        label = params.get("label")
        index = params.get("index")

        locator = resolve_locator(page, target)
        try:
            if value is not None:
                selected = await locator.select_option(value=str(value), timeout=timeout_ms)
            elif label is not None:
                selected = await locator.select_option(label=str(label), timeout=timeout_ms)
            elif index is not None:
                selected = await locator.select_option(index=int(index), timeout=timeout_ms)
            else:
                raise ActionExecutionError("Select action requires 'value', 'label', or 'index'")

            return (
                {"selected": selected},
                {"target": target.model_dump(), "selected": selected},
            )
        except PlaywrightTimeoutError as exc:
            raise ElementNotFoundError(f"Target select element not found: {target}") from exc

    async def _scroll(
        self,
        page: Page,
        target: Any | None,
        params: dict[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        if target:
            locator = resolve_locator(page, target)
            await locator.scroll_into_view_if_needed()
            return ({"scrolled_to_element": True}, {"target": target.model_dump()})

        delta_x = int(params.get("delta_x", params.get("x", 0)))
        delta_y = int(params.get("delta_y", params.get("y", 400)))

        await page.mouse.wheel(delta_x, delta_y)
        return (
            {"scrolled_delta": {"x": delta_x, "y": delta_y}},
            {"delta_x": delta_x, "delta_y": delta_y},
        )

    async def _press_key(
        self,
        page: Page,
        target: Any | None,
        params: dict[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        key = params.get("key")
        if not key:
            raise ActionExecutionError(
                "Action 'browser.press_key' requires 'key' parameter (e.g. 'Enter')"
            )

        if target:
            locator = resolve_locator(page, target)
            await locator.press(str(key))
        else:
            await page.keyboard.press(str(key))

        return ({"pressed_key": key}, {"key": key})

    async def _wait(
        self,
        page: Page,
        target: Any | None,
        params: dict[str, Any],
        timeout_ms: int,
    ) -> tuple[Any, dict[str, Any]]:
        if target:
            locator = resolve_locator(page, target)
            state = params.get("state", "visible")
            await locator.wait_for(state=state, timeout=timeout_ms)
            return ({"waited_for": target.model_dump(), "state": state}, {"state": state})

        duration_ms = int(params.get("duration_ms", params.get("ms", 1000)))
        await asyncio.sleep(min(duration_ms, timeout_ms) / 1000.0)
        return ({"waited_ms": duration_ms}, {"duration_ms": duration_ms})

    async def _upload(
        self,
        page: Page,
        target: Any | None,
        params: dict[str, Any],
        timeout_ms: int,
    ) -> tuple[Any, dict[str, Any]]:
        if not target:
            raise ActionExecutionError("Upload action requires target file input specification")

        file_path_str = params.get("file_path") or params.get("path")
        if not file_path_str:
            raise ActionExecutionError("Upload action requires 'file_path' parameter")

        file_path = Path(file_path_str).resolve()
        if not file_path.exists():
            raise ActionExecutionError(f"Upload source file does not exist: {file_path}")

        locator = resolve_locator(page, target)
        try:
            await locator.set_input_files(str(file_path), timeout=timeout_ms)
            return (
                {"uploaded": file_path.name, "size": file_path.stat().st_size},
                {"filename": file_path.name, "path": str(file_path)},
            )
        except PlaywrightTimeoutError as exc:
            raise ElementNotFoundError(
                f"File input element not found for upload: {target}"
            ) from exc

    async def _new_tab(self, params: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        url = params.get("url")
        new_page = await self.context.new_page()
        if url:
            await new_page.goto(str(url))
        return (
            {"tab_count": len(self.context.pages), "url": new_page.url},
            {"tab_count": len(self.context.pages)},
        )

    async def _close_tab(self, page: Page) -> tuple[Any, dict[str, Any]]:
        await page.close()
        remaining = len(self.context.pages)
        return ({"closed": True, "remaining_tabs": remaining}, {"remaining_tabs": remaining})
