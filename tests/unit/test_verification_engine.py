"""Unit tests for deterministic post-condition verification engine."""

import pytest
from atlas_browser.config import BrowserConfig
from atlas_browser.driver import PlaywrightBrowserDriver
from atlas_core.contracts.action import ExpectedState
from atlas_verification.engine import VerificationEngine

from tests.fixtures.synthetic_server import SyntheticServer


@pytest.fixture(scope="module")
def synthetic_server():
    server = SyntheticServer()
    base_url = server.start()
    yield base_url
    server.stop()


@pytest.mark.asyncio
async def test_verification_element_visible_and_hidden(synthetic_server):
    driver = PlaywrightBrowserDriver(BrowserConfig(headless=True, allowed_domains=["127.0.0.1"]))
    await driver.connect()

    page = driver.active_page
    await page.goto(f"{synthetic_server}/interactive")

    engine = VerificationEngine()

    # 1. Element visible match
    res_vis = await engine.verify(
        ExpectedState(condition="element_visible", target="#btn-primary"),
        page=page,
    )
    assert res_vis.verified
    assert res_vis.error is None

    # 2. Element visible failure (non-existent element)
    res_fail = await engine.verify(
        ExpectedState(condition="element_visible", target="#non-existent-button", timeout_ms=500),
        page=page,
    )
    assert not res_fail.verified
    assert res_fail.error is not None

    # 3. Element hidden match (non-existent element is hidden)
    res_hidden = await engine.verify(
        ExpectedState(condition="element_hidden", target="#absent-element", timeout_ms=500),
        page=page,
    )
    assert res_hidden.verified

    # 4. Text present match
    res_text = await engine.verify(
        ExpectedState(condition="text_present", target="Primary Button"),
        page=page,
    )
    assert res_text.verified

    # 5. URL matches
    res_url = await engine.verify(
        ExpectedState(condition="url_matches", target=r"/interactive$"),
        page=page,
    )
    assert res_url.verified

    await driver.disconnect()


@pytest.mark.asyncio
async def test_verification_file_downloaded(tmp_path):
    engine = VerificationEngine()

    test_file = tmp_path / "export.csv"
    test_file.write_text("col1,col2\nval1,val2\n", encoding="utf-8")

    # Match existing file
    res = await engine.verify(
        ExpectedState(condition="file_downloaded", target="export.csv"),
        download_dir=tmp_path,
    )
    assert res.verified

    # Empty file check
    empty_file = tmp_path / "empty.csv"
    empty_file.write_text("", encoding="utf-8")
    res_empty = await engine.verify(
        ExpectedState(condition="file_downloaded", target="empty.csv"),
        download_dir=tmp_path,
    )
    assert not res_empty.verified
    assert "0 bytes" in res_empty.error
