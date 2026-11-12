"""Unit tests for browser action execution and policy firewall integration."""

import pytest
from atlas_browser.config import BrowserConfig
from atlas_browser.driver import PlaywrightBrowserDriver
from atlas_core.contracts.action import ActionTarget, ComputerAction, ExpectedState
from atlas_policy.firewall import ActionFirewall

from tests.fixtures.synthetic_server import SyntheticServer


@pytest.fixture(scope="module")
def synthetic_server():
    server = SyntheticServer()
    base_url = server.start()
    yield base_url
    server.stop()


@pytest.mark.asyncio
async def test_browser_action_navigation_and_form_filling(synthetic_server):
    driver = PlaywrightBrowserDriver(
        config=BrowserConfig(headless=True, allowed_domains=["127.0.0.1"])
    )
    await driver.connect()

    # 1. Action: Navigate to /login
    nav_action = ComputerAction(
        action_id="act_nav",
        task_id="t_form",
        session_id="s1",
        action_type="browser.navigate",
        parameters={"url": f"{synthetic_server}/login"},
        expected_state=ExpectedState(condition="text_present", target="User Authentication"),
        idempotency_key="k_nav",
    )
    res_nav = await driver.execute(nav_action)
    assert res_nav.success
    assert res_nav.output["title"] == "ATLAS Login"

    # 2. Action: Fill username
    fill_user = ComputerAction(
        action_id="act_user",
        task_id="t_form",
        session_id="s1",
        action_type="browser.fill",
        target=ActionTarget(strategy="css", parameters={"selector": "#username"}),
        parameters={"value": "alice"},
        idempotency_key="k_user",
    )
    res_user = await driver.execute(fill_user)
    assert res_user.success

    # 3. Action: Type password
    type_pass = ComputerAction(
        action_id="act_pass",
        task_id="t_form",
        session_id="s1",
        action_type="browser.type",
        target=ActionTarget(strategy="css", parameters={"selector": "#password"}),
        parameters={"text": "supersecretpassword"},
        idempotency_key="k_pass",
    )
    res_pass = await driver.execute(type_pass)
    assert res_pass.success

    # 4. Action: Click Sign In button with verification of authenticated status
    click_btn = ComputerAction(
        action_id="act_submit",
        task_id="t_form",
        session_id="s1",
        action_type="browser.click",
        target=ActionTarget(
            strategy="accessible_role", parameters={"role": "button", "name": "Sign In"}
        ),
        expected_state=ExpectedState(condition="text_present", target="Authenticated"),
        idempotency_key="k_sub",
    )
    res_click = await driver.execute(click_btn)
    assert res_click.success
    assert res_click.evidence["verification"]["verified"]

    await driver.disconnect()


@pytest.mark.asyncio
async def test_browser_action_firewall_denial(synthetic_server):
    firewall = ActionFirewall(
        allowed_domains=["allowed.example.com"],
        blocked_domains=["malicious.example.com"],
    )
    driver = PlaywrightBrowserDriver(
        config=BrowserConfig(headless=True),
        firewall=firewall,
    )
    await driver.connect()

    # Attempt navigation to blocked domain
    blocked_action = ComputerAction(
        action_id="act_blocked",
        task_id="t_sec",
        session_id="s1",
        action_type="browser.navigate",
        parameters={"url": "http://malicious.example.com/exploit"},
        idempotency_key="k_block",
    )
    result = await driver.execute(blocked_action)
    assert not result.success
    assert "denied by policy firewall" in result.error

    await driver.disconnect()


@pytest.mark.asyncio
async def test_browser_action_dropdown_and_coordinates(synthetic_server):
    driver = PlaywrightBrowserDriver(
        config=BrowserConfig(headless=True, allowed_domains=["127.0.0.1"])
    )
    await driver.connect()

    await driver.execute(
        ComputerAction(
            action_id="act_nav_int",
            task_id="t1",
            session_id="s1",
            action_type="browser.navigate",
            parameters={"url": f"{synthetic_server}/interactive"},
            idempotency_key="k1",
        )
    )

    # 1. Select dropdown option
    select_action = ComputerAction(
        action_id="act_sel",
        task_id="t1",
        session_id="s1",
        action_type="browser.select",
        target=ActionTarget(strategy="css", parameters={"selector": "#country-select"}),
        parameters={"value": "ca"},
        expected_state=ExpectedState(
            condition="value_equals", target="#country-select", value="ca"
        ),
        idempotency_key="k2",
    )
    res_sel = await driver.execute(select_action)
    assert res_sel.success

    # 2. Click button by role with text verification
    click_role = ComputerAction(
        action_id="act_role",
        task_id="t1",
        session_id="s1",
        action_type="browser.click",
        target=ActionTarget(
            strategy="accessible_role", parameters={"role": "button", "name": "Primary Button"}
        ),
        expected_state=ExpectedState(condition="text_present", target="Clicked Primary"),
        idempotency_key="k3",
    )
    res_role = await driver.execute(click_role)
    assert res_role.success

    await driver.disconnect()


@pytest.mark.asyncio
async def test_browser_action_upload(synthetic_server, tmp_path):
    driver = PlaywrightBrowserDriver(
        config=BrowserConfig(headless=True, allowed_domains=["127.0.0.1"])
    )
    await driver.connect()

    # Create dummy upload file
    upload_file = tmp_path / "sample.txt"
    upload_file.write_text("Test upload payload", encoding="utf-8")

    await driver.execute(
        ComputerAction(
            action_id="act_nav_up",
            task_id="t1",
            session_id="s1",
            action_type="browser.navigate",
            parameters={"url": f"{synthetic_server}/upload"},
            idempotency_key="k_up_nav",
        )
    )

    upload_action = ComputerAction(
        action_id="act_upload",
        task_id="t1",
        session_id="s1",
        action_type="browser.upload",
        target=ActionTarget(strategy="css", parameters={"selector": "#file-input"}),
        parameters={"file_path": str(upload_file)},
        expected_state=ExpectedState(condition="text_present", target="File selected: sample.txt"),
        idempotency_key="k_upload",
    )
    res_upload = await driver.execute(upload_action)
    assert res_upload.success
    assert res_upload.output["uploaded"] == "sample.txt"

    await driver.disconnect()
