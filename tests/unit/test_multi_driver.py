"""Unit tests for DesktopDriver and DriverRegistry multi-driver abstraction."""

from datetime import UTC, datetime

import pytest
from atlas_browser.desktop import DesktopDriver
from atlas_browser.registry import DriverRegistry
from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.observation import Observation
from atlas_core.runtime.driver import ComputerDriver, DriverHealth


class MockBrowserDriver(ComputerDriver):
    """Stub browser driver for registry testing."""

    def __init__(self) -> None:
        self.connected = False
        self.executed_actions: list[ComputerAction] = []

    async def connect(self, config: dict | None = None) -> dict:
        self.connected = True
        return {"status": "browser_connected"}

    async def observe(self) -> Observation:
        return Observation(
            observation_id="obs_browser_1",
            task_id="test_task",
            session_id="browser_sess",
            timestamp=datetime.now(UTC),
            window_title="Example Domain",
            metadata={"url": "https://example.com"},
        )

    async def execute(self, action: ComputerAction) -> ActionResult:
        self.executed_actions.append(action)
        return ActionResult(
            action_id=action.action_id,
            success=True,
            output={"browser_ok": True},
            duration_ms=10,
        )

    async def health_check(self) -> DriverHealth:
        return DriverHealth(
            status="ok" if self.connected else "disconnected",
            driver_type="browser",
            connected=self.connected,
        )

    async def disconnect(self) -> None:
        self.connected = False


def _make_action(action_type: str, parameters: dict | None = None) -> ComputerAction:
    return ComputerAction(
        action_id=f"act_{action_type.replace('.', '_')}",
        task_id="test_task",
        session_id="test_sess",
        action_type=action_type,
        parameters=parameters or {},
        idempotency_key=f"idem_{action_type}",
    )


@pytest.mark.asyncio
async def test_desktop_driver_lifecycle() -> None:
    """Verify DesktopDriver connect, observe, action execution, and disconnect."""
    driver = DesktopDriver(screen_size=(1280, 720), default_window="Desktop")

    # Before connect
    with pytest.raises(RuntimeError, match="not connected"):
        await driver.observe()

    with pytest.raises(RuntimeError, match="not connected"):
        await driver.execute(_make_action("desktop.click", {"x": 100, "y": 100}))

    # Connect
    conn_res = await driver.connect({"initial_window": "Finder"})
    assert conn_res["status"] == "connected"
    assert driver.connected is True
    assert driver.active_window == "Finder"

    # Observe
    obs = await driver.observe()
    assert obs.window_title == "Finder"
    assert obs.accessibility_tree is not None
    assert obs.dom_snapshot is not None
    assert obs.metadata["driver_type"] == "desktop"

    # Execute click
    res = await driver.execute(_make_action("desktop.click", {"x": 500, "y": 300}))
    assert res.success is True
    assert res.output["clicked_at"] == [500, 300]
    assert driver.cursor_pos == (500, 300)

    # Click with boundary clipping
    res_clip = await driver.execute(_make_action("desktop.click", {"x": 9999, "y": 9999}))
    assert res_clip.success is True
    assert res_clip.output["clicked_at"] == [1280, 720]

    # Type & press key
    type_res = await driver.execute(_make_action("desktop.type", {"text": "hello world"}))
    assert type_res.success is True
    assert "hello world" in driver.keyboard_buffer

    key_res = await driver.execute(_make_action("desktop.press_key", {"key": "Return"}))
    assert key_res.success is True
    assert "<Return>" in driver.keyboard_buffer

    # Launch app & focus window
    launch_res = await driver.execute(_make_action("desktop.launch_app", {"app_name": "Terminal"}))
    assert launch_res.success is True
    assert driver.active_window == "Terminal"
    assert "Terminal" in driver.open_windows

    focus_res = await driver.execute(_make_action("desktop.focus_window", {"title": "Desktop"}))
    assert focus_res.success is True
    assert driver.active_window == "Desktop"

    # Screenshot action
    sc_res = await driver.execute(_make_action("desktop.screenshot", {}))
    assert sc_res.success is True

    # Health check
    health = await driver.health_check()
    assert health.status == "ok"
    assert health.connected is True
    assert health.driver_type == "desktop"

    # Disconnect
    await driver.disconnect()
    assert driver.connected is False


@pytest.mark.asyncio
async def test_driver_registry_routing() -> None:
    """Verify DriverRegistry routes actions by prefix and manages defaults."""
    registry = DriverRegistry()

    browser = MockBrowserDriver()
    desktop = DesktopDriver()

    registry.register("browser", browser, is_default=True)
    registry.register("desktop", desktop)

    assert registry.default_driver is browser
    assert registry.active_driver is browser

    # Connect all
    conn_map = await registry.connect()
    assert "browser" in conn_map
    assert "desktop" in conn_map

    # Routing browser action
    act_browser = _make_action("browser.navigate", {"url": "https://example.com"})
    res_b = await registry.execute(act_browser)
    assert res_b.success is True
    assert res_b.output["browser_ok"] is True
    assert len(browser.executed_actions) == 1

    # Routing desktop action
    act_desktop = _make_action("desktop.click", {"x": 200, "y": 150})
    res_d = await registry.execute(act_desktop)
    assert res_d.success is True
    assert res_d.output["clicked_at"] == [200, 150]

    # Fallback to default driver for unprefixed action
    act_generic = _make_action("custom_wait", {})
    res_gen = await registry.execute(act_generic)
    assert res_gen.success is True
    assert len(browser.executed_actions) == 2

    # Observe routes to active driver
    obs = await registry.observe()
    assert obs.window_title == "Example Domain"

    # Switch active driver to desktop
    registry.set_active_driver("desktop")
    assert registry.active_driver is desktop
    obs_desktop = await registry.observe()
    assert obs_desktop.metadata["driver_type"] == "desktop"

    # Health check aggregation
    health = await registry.health_check()
    assert health.status == "ok"
    assert health.connected is True
    assert "browser" in health.details
    assert "desktop" in health.details

    # Disconnect all
    await registry.disconnect()
    assert browser.connected is False
    assert desktop.connected is False


@pytest.mark.asyncio
async def test_driver_registry_unregistered_error() -> None:
    """Verify registry raises appropriate error when action has no matching driver."""
    registry = DriverRegistry()
    with pytest.raises(RuntimeError, match="No drivers registered"):
        await registry.observe()

    with pytest.raises(ValueError, match="No driver registered"):
        await registry.execute(_make_action("terminal.exec", {}))
