"""Unit tests for PlaywrightBrowserDriver lifecycle and ComputerDriver protocol."""

import pytest
from atlas_browser.config import BrowserConfig
from atlas_browser.driver import PlaywrightBrowserDriver
from atlas_core.runtime.driver import ComputerDriver

from tests.fixtures.synthetic_server import SyntheticServer


@pytest.fixture(scope="module")
def synthetic_server():
    server = SyntheticServer()
    base_url = server.start()
    yield base_url
    server.stop()


@pytest.mark.asyncio
async def test_driver_protocol_conformance():
    driver = PlaywrightBrowserDriver(BrowserConfig(headless=True))
    assert isinstance(driver, ComputerDriver)


@pytest.mark.asyncio
async def test_driver_connect_health_and_disconnect(synthetic_server):
    config = BrowserConfig(headless=True, allowed_domains=["127.0.0.1"])
    driver = PlaywrightBrowserDriver(config=config)

    # Pre-connect health check
    health_before = await driver.health_check()
    assert health_before.status == "disconnected"
    assert not health_before.connected

    # Connect
    context = await driver.connect()
    assert context is not None

    # Post-connect health check
    health = await driver.health_check()
    assert health.status == "ok"
    assert health.connected
    assert health.details["active_tabs"] >= 1

    # Clean disconnect
    await driver.disconnect()
    health_after = await driver.health_check()
    assert health_after.status == "disconnected"


@pytest.mark.asyncio
async def test_driver_session_isolation(synthetic_server):
    # Create two separate drivers
    driver1 = PlaywrightBrowserDriver(BrowserConfig(headless=True))
    driver2 = PlaywrightBrowserDriver(BrowserConfig(headless=True))

    await driver1.connect()
    await driver2.connect()

    # Verify separate browser contexts
    assert driver1.context != driver2.context
    assert driver1._driver_id != driver2._driver_id

    await driver1.disconnect()
    await driver2.disconnect()
