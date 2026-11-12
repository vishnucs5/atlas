"""Unit tests for browser file downloads, error handling, and recovery diagnostics."""

import pytest
from atlas_browser.config import BrowserConfig
from atlas_browser.driver import PlaywrightBrowserDriver
from atlas_core.contracts.action import ActionTarget, ComputerAction, ExpectedState

from tests.fixtures.synthetic_server import SyntheticServer


@pytest.fixture(scope="module")
def synthetic_server():
    server = SyntheticServer()
    base_url = server.start()
    yield base_url
    server.stop()


@pytest.mark.asyncio
async def test_browser_download_interception(synthetic_server, tmp_path):
    download_dir = tmp_path / "downloads"
    config = BrowserConfig(
        headless=True,
        allowed_domains=["127.0.0.1"],
        download_dir=download_dir,
    )
    driver = PlaywrightBrowserDriver(config=config)
    await driver.connect()

    # 1. Navigate to home page where download link is present
    nav_action = ComputerAction(
        action_id="act_nav_home",
        task_id="task_dl_001",
        session_id=driver._driver_id,
        action_type="browser.navigate",
        parameters={"url": synthetic_server},
        expected_state=ExpectedState(condition="text_present", target="Download File"),
        idempotency_key="nav_home",
    )
    res_nav = await driver.execute(nav_action)
    assert res_nav.success

    # 2. Click download link and verify file is downloaded
    dl_action = ComputerAction(
        action_id="act_click_download",
        task_id="task_dl_001",
        session_id=driver._driver_id,
        action_type="browser.click",
        target=ActionTarget(strategy="css", value="#nav-download"),
        expected_state=ExpectedState(
            condition="file_downloaded",
            target="data.csv",
        ),
        idempotency_key="click_dl",
    )
    res_dl = await driver.execute(dl_action)
    assert res_dl.success
    assert res_dl.evidence["verification"]["verified"]

    # Verify download file exists on disk and is contained
    dl_file = download_dir / "data.csv"
    assert dl_file.exists()
    assert b"1,alpha,100" in dl_file.read_bytes()

    # Check driver observation metadata includes downloads
    obs = await driver.observe()
    assert len(obs.metadata["downloads"]) >= 1
    assert obs.metadata["downloads"][0]["filename"] == "data.csv"
    assert obs.metadata["downloads"][0]["size_bytes"] > 0

    await driver.disconnect()


@pytest.mark.asyncio
async def test_browser_element_not_found_handling(synthetic_server):
    config = BrowserConfig(headless=True, allowed_domains=["127.0.0.1"], timeout_ms=500)
    driver = PlaywrightBrowserDriver(config=config)
    await driver.connect()

    await driver.active_page.goto(f"{synthetic_server}/interactive")

    # Attempt to click non-existent selector
    action = ComputerAction(
        action_id="act_click_missing",
        task_id="task_err_001",
        session_id=driver._driver_id,
        action_type="browser.click",
        target=ActionTarget(strategy="css", value="#non-existent-button-999"),
        idempotency_key="err_missing",
    )

    result = await driver.execute(action)
    assert not result.success
    assert "not found" in result.error.lower() or "timed out" in result.error.lower()

    await driver.disconnect()


@pytest.mark.asyncio
async def test_browser_health_check_states():
    driver = PlaywrightBrowserDriver(BrowserConfig(headless=True))

    # 1. Before connection
    health_before = await driver.health_check()
    assert not health_before.connected
    assert health_before.status == "disconnected"

    # 2. While connected
    await driver.connect()
    health_connected = await driver.health_check()
    assert health_connected.connected
    assert health_connected.status == "ok"
    assert health_connected.driver_type == "browser.playwright.chromium"

    # 3. After clean disconnect
    await driver.disconnect()
    health_after = await driver.health_check()
    assert not health_after.connected
    assert health_after.status == "disconnected"
