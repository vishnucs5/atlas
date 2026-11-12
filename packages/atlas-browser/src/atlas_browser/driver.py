"""Playwright-based browser driver implementing the ComputerDriver protocol."""

import time
import uuid
from pathlib import Path
from typing import Any

from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.observation import Observation
from atlas_core.contracts.policy import PolicyDecisionType
from atlas_core.runtime.driver import ComputerDriver, DriverHealth
from atlas_core.runtime.exceptions import DriverError
from atlas_observation.capture import capture_observation
from atlas_policy.firewall import ActionFirewall
from atlas_verification.engine import VerificationEngine
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from atlas_browser.actions import BrowserActionExecutor
from atlas_browser.config import BrowserConfig
from atlas_browser.downloads import DownloadManager
from atlas_browser.network import NetworkMonitor


class PlaywrightBrowserDriver(ComputerDriver):
    """Playwright Chromium driver implementing the ComputerDriver protocol."""

    def __init__(
        self,
        config: BrowserConfig | None = None,
        firewall: ActionFirewall | None = None,
        verification_engine: VerificationEngine | None = None,
    ) -> None:
        self.config = config or BrowserConfig()
        self.firewall = firewall or ActionFirewall(
            allowed_domains=self.config.allowed_domains,
            blocked_domains=self.config.blocked_domains,
        )
        self.verification_engine = verification_engine or VerificationEngine()

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._active_page: Page | None = None

        self._network_monitor: NetworkMonitor = NetworkMonitor()
        self._download_manager: DownloadManager | None = None
        self._executor: BrowserActionExecutor | None = None

        self._connected: bool = False
        self._driver_id: str = f"driver_browser_{uuid.uuid4().hex[:8]}"

    @property
    def active_page(self) -> Page:
        """Return the active Playwright page."""
        if not self._active_page or self._active_page.is_closed():
            if self._context and self._context.pages:
                self._active_page = self._context.pages[-1]
            else:
                raise DriverError("No active page available in browser context")
        return self._active_page

    @property
    def context(self) -> BrowserContext:
        """Return the isolated browser context."""
        if not self._context:
            raise DriverError("Browser context is not initialized. Call connect() first.")
        return self._context

    async def connect(self, config: dict[str, Any] | None = None) -> Any:
        """Launch Chromium browser and establish isolated BrowserContext."""
        if self._connected and self._browser and self._browser.is_connected():
            return self._context

        if config:
            self.config = BrowserConfig(**{**self.config.model_dump(), **config})

        self._playwright = await async_playwright().start()

        # Launch Chromium process
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo_ms,
        )

        # Configure isolated download directory
        download_path = self.config.download_dir or Path(".atlas/downloads") / self._driver_id
        download_path = Path(download_path).resolve()
        download_path.mkdir(parents=True, exist_ok=True)
        self._download_manager = DownloadManager(download_path)

        # Create isolated browser context (isolated storage, cookies, cache)
        self._context = await self._browser.new_context(
            viewport={
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
            accept_downloads=self.config.accept_downloads,
            ignore_https_errors=self.config.ignore_https_errors,
            user_agent=self.config.user_agent,
        )
        self._context.set_default_timeout(self.config.timeout_ms)
        self._context.set_default_navigation_timeout(self.config.navigation_timeout_ms)

        # Open initial page
        self._active_page = await self._context.new_page()

        # Attach monitors
        self._network_monitor.attach(self._active_page)
        self._download_manager.attach(self._active_page)

        self._executor = BrowserActionExecutor(
            context=self._context,
            download_dir=download_path,
        )

        self._connected = True
        return self._context

    async def observe(self) -> Observation:
        """Capture the current multimodal and structured state of the browser."""
        if not self._connected or not self._active_page:
            raise DriverError("Cannot observe: browser is not connected")

        page = self.active_page
        obs = await capture_observation(
            page=page,
            task_id="active_task",
            session_id=self._driver_id,
            include_screenshot=True,
            include_interactive_elements=True,
        )
        # Augment with network diagnostics and downloaded files
        obs.metadata["network_summary"] = self._network_monitor.get_summary()
        if self._download_manager:
            obs.metadata["downloads"] = self._download_manager.get_downloaded_files()

        return obs

    async def execute(self, action: ComputerAction) -> ActionResult:
        """Execute action through the Action Firewall and verify expected state."""
        start_time = time.perf_counter()

        if not self._connected or not self._executor:
            raise DriverError("Driver is not connected. Call connect() before execute().")

        # GATE 1: Action Firewall Authorization (Constitution Rule 2)
        policy_decision = self.firewall.evaluate(action)
        if policy_decision.decision == PolicyDecisionType.DENY:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=False,
                error=f"Action denied by policy firewall: {policy_decision.reason}",
                duration_ms=duration_ms,
                evidence={
                    "policy_decision": policy_decision.model_dump(),
                    "risk_level": policy_decision.risk_level.value,
                },
            )

        if policy_decision.decision == PolicyDecisionType.REQUIRE_APPROVAL:
            # Check if an explicit approval grant is provided in parameters
            if not action.parameters.get("approval_granted", False):
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                return ActionResult(
                    action_id=action.action_id,
                    success=False,
                    error=f"Action requires explicit user approval: {policy_decision.reason}",
                    duration_ms=duration_ms,
                    evidence={
                        "policy_decision": policy_decision.model_dump(),
                        "approval_required": True,
                        "risk_level": policy_decision.risk_level.value,
                    },
                )

        # GATE 2: Execution in Browser Context
        try:
            page = self.active_page
            output, evidence = await self._executor.execute(action, page)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
                evidence={"policy_decision": policy_decision.model_dump()},
            )

        # GATE 3: Deterministic Post-Condition Verification (Constitution Rule 7)
        verification_passed = True
        verification_data: dict[str, Any] = {}
        if action.expected_state:
            download_dir = self._download_manager.download_dir if self._download_manager else None
            v_res = await self.verification_engine.verify(
                expected=action.expected_state,
                page=self.active_page,
                download_dir=download_dir,
            )
            verification_data = v_res.model_dump()
            if not v_res.verified:
                verification_passed = False

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        evidence["policy_decision"] = policy_decision.model_dump()
        if verification_data:
            evidence["verification"] = verification_data

        return ActionResult(
            action_id=action.action_id,
            success=verification_passed,
            output=output,
            error=verification_data.get("error") if not verification_passed else None,
            duration_ms=duration_ms,
            evidence=evidence,
        )

    async def health_check(self) -> DriverHealth:
        """Check browser connection, page responsiveness, and process status."""
        if not self._connected or not self._browser:
            return DriverHealth(
                status="disconnected",
                driver_type="browser.playwright.chromium",
                connected=False,
                details={"error": "Driver not connected"},
            )

        if not self._browser.is_connected():
            return DriverHealth(
                status="crashed",
                driver_type="browser.playwright.chromium",
                connected=False,
                details={"error": "Underlying browser process terminated"},
            )

        try:
            page = self.active_page
            title = await page.title()
            return DriverHealth(
                status="ok",
                driver_type="browser.playwright.chromium",
                connected=True,
                details={
                    "active_tabs": len(self.context.pages),
                    "current_url": page.url,
                    "title": title,
                    "network": self._network_monitor.get_summary(),
                },
            )
        except Exception as exc:
            return DriverHealth(
                status="degraded",
                driver_type="browser.playwright.chromium",
                connected=True,
                details={"error": str(exc)},
            )

    async def disconnect(self) -> None:
        """Cleanly tear down context, browser, and playwright engine."""
        self._connected = False
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass

        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass

        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass

        self._active_page = None
        self._context = None
        self._browser = None
        self._playwright = None
