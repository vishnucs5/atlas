"""Unit tests for Observation Engine (DOM, accessibility, screenshots)."""

import pytest
from atlas_browser.config import BrowserConfig
from atlas_browser.driver import PlaywrightBrowserDriver
from atlas_observation.accessibility import extract_accessibility_tree
from atlas_observation.capture import capture_observation, capture_screenshot
from atlas_observation.dom import extract_dom_snapshot, extract_interactive_elements

from tests.fixtures.synthetic_server import SyntheticServer


@pytest.fixture(scope="module")
def synthetic_server():
    server = SyntheticServer()
    base_url = server.start()
    yield base_url
    server.stop()


@pytest.mark.asyncio
async def test_observation_engine_capabilities(synthetic_server):
    driver = PlaywrightBrowserDriver(BrowserConfig(headless=True, allowed_domains=["127.0.0.1"]))
    await driver.connect()

    page = driver.active_page
    await page.goto(f"{synthetic_server}/interactive")

    # 1. Test DOM snapshot
    dom = await extract_dom_snapshot(page)
    assert "<title>Interactive Controls</title>" in dom
    assert "btn-primary" in dom

    # 2. Test interactive elements extraction
    interactive = await extract_interactive_elements(page)
    assert len(interactive) >= 3
    tags = [elem["tag"] for elem in interactive]
    assert "button" in tags
    assert "select" in tags

    # 3. Test accessibility tree snapshot
    a11y = await extract_accessibility_tree(page)
    assert a11y is not None
    assert "nodes" in a11y and len(a11y["nodes"]) > 0

    # 4. Test screenshot capture
    img_bytes = await capture_screenshot(page)
    assert len(img_bytes) > 1000
    assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic header

    # 5. Full structured Observation contract
    obs = await capture_observation(page, task_id="task_test_obs", session_id="sess_123")
    assert obs.observation_id.startswith("obs_")
    assert obs.window_title == "Interactive Controls"
    assert obs.screenshot_ref is not None
    assert obs.screenshot_ref.startswith("data:image/png;base64,")
    assert len(obs.metadata["interactive_elements"]) >= 3

    await driver.disconnect()
