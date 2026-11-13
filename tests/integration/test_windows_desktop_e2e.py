"""Integration tests for native Windows interactive desktop automation on real Windows sessions."""

import sys

import pytest
from atlas_browser.desktop import DesktopDriver
from atlas_core.contracts.action import ComputerAction


def _make_desktop_action(action_type: str, parameters: dict | None = None) -> ComputerAction:
    return ComputerAction(
        action_id=f"act_desk_{action_type.replace('.', '_')}",
        task_id="task_win_desktop",
        session_id="sess_win_desktop",
        action_type=action_type,
        parameters=parameters or {},
        idempotency_key=f"idem_{action_type}",
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows session")
@pytest.mark.asyncio
async def test_windows_native_desktop_automation() -> None:
    """Verify Windows native desktop driver detection, process launch, interaction, and cleanup."""
    import ctypes

    expected_w = int(ctypes.windll.user32.GetSystemMetrics(0))
    expected_h = int(ctypes.windll.user32.GetSystemMetrics(1))

    # Initialize without hardcoded screen_size to test auto-detection
    driver = DesktopDriver(native_mode=True)
    assert driver.screen_width == expected_w
    assert driver.screen_height == expected_h

    # Connect to Windows desktop session
    conn_info = await driver.connect({"initial_window": "WindowsDesktop", "native_mode": True})
    assert conn_info["status"] == "connected"
    assert conn_info["native_mode"] is True
    assert driver.connected is True

    # 1. Capture initial desktop observation
    obs = await driver.observe()
    assert obs.window_title == "WindowsDesktop"
    assert obs.metadata["screen_size"] == [expected_w, expected_h]
    assert obs.metadata["platform"] == "win32"
    assert obs.metadata["native_mode"] is True

    # 2. Launch a native Windows application (notepad.exe)
    launch_act = _make_desktop_action(
        "desktop.launch_app", {"app_name": "notepad.exe", "native": True}
    )
    res_launch = await driver.execute(launch_act)
    assert res_launch.success is True
    assert res_launch.output["launched"] == "notepad.exe"
    assert res_launch.output["active_window"] == "notepad.exe"
    pid = res_launch.output["pid"]
    assert pid is not None, "Native Windows launch must return process ID"
    assert "notepad.exe" in driver.native_processes

    # 3. Move cursor and click within real screen coordinates
    target_x = min(500, expected_w - 50)
    target_y = min(400, expected_h - 50)
    move_act = _make_desktop_action("desktop.move_cursor", {"x": target_x, "y": target_y})
    res_move = await driver.execute(move_act)
    assert res_move.success is True
    assert driver.cursor_pos == (target_x, target_y)

    click_act = _make_desktop_action("desktop.click", {"x": target_x, "y": target_y})
    res_click = await driver.execute(click_act)
    assert res_click.success is True
    assert res_click.output["clicked_at"] == [target_x, target_y]

    # 4. Type text and press keys
    type_act = _make_desktop_action(
        "desktop.type", {"text": "ATLAS Autonomous System Verification"}
    )
    res_type = await driver.execute(type_act)
    assert res_type.success is True
    assert res_type.output["typed_length"] == len("ATLAS Autonomous System Verification")

    key_act = _make_desktop_action("desktop.press_key", {"key": "Enter"})
    res_key = await driver.execute(key_act)
    assert res_key.success is True
    assert res_key.output["pressed_key"] == "Enter"

    # 5. Capture native screenshot action
    shot_act = _make_desktop_action("desktop.screenshot", {})
    res_shot = await driver.execute(shot_act)
    assert res_shot.success is True
    assert res_shot.output["width"] == expected_w
    assert res_shot.output["height"] == expected_h

    # 6. Verify health check reports native Windows telemetry
    health = await driver.health_check()
    assert health.status == "ok"
    assert health.details["platform"] == "win32"
    assert health.details["native_mode"] is True
    assert "notepad.exe" in health.details["native_processes"]

    # 7. Terminate native Windows application
    close_act = _make_desktop_action("desktop.close_app", {"app_name": "notepad.exe"})
    res_close = await driver.execute(close_act)
    assert res_close.success is True
    assert res_close.output["closed"] == "notepad.exe"
    assert res_close.output["terminated_native"] is True
    assert "notepad.exe" not in driver.native_processes
    assert "notepad.exe" not in driver.open_windows

    # 8. Clean disconnection
    await driver.disconnect()
    assert driver.connected is False
    assert len(driver.native_processes) == 0
