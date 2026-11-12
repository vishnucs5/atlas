"""DesktopDriver implementing ComputerDriver for desktop and OS automation."""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.observation import Observation
from atlas_core.runtime.driver import ComputerDriver, DriverHealth


class DesktopDriver(ComputerDriver):
    """Execution driver for desktop applications and operating system automation.

    Provides hermetic, synthetic desktop automation supporting mouse coordinates,
    keyboard typing, window focusing, and accessibility tree inspection.
    """

    def __init__(
        self,
        screen_size: tuple[int, int] = (1920, 1080),
        default_window: str = "Desktop",
    ) -> None:
        self.screen_width, self.screen_height = screen_size
        self.default_window = default_window
        self.active_window = default_window
        self.open_windows: list[str] = [default_window]
        self.cursor_pos: tuple[int, int] = (self.screen_width // 2, self.screen_height // 2)
        self.keyboard_buffer: list[str] = []
        self.connected: bool = False
        self.session_id: str | None = None

    async def connect(self, config: dict[str, Any] | None = None) -> Any:
        """Initialize desktop environment connection and virtual desktop surface."""
        cfg = config or {}
        self.session_id = cfg.get("session_id", f"desktop_sess_{uuid.uuid4().hex[:8]}")
        self.active_window = cfg.get("initial_window", self.default_window)
        if self.active_window not in self.open_windows:
            self.open_windows.append(self.active_window)
        self.connected = True
        return {"status": "connected", "session_id": self.session_id}

    async def observe(self) -> Observation:
        """Capture the current structured and multimodal state of the desktop."""
        if not self.connected:
            raise RuntimeError("DesktopDriver is not connected. Call connect() first.")

        obs_id = f"obs_desk_{uuid.uuid4().hex[:8]}"
        session_id = self.session_id or "desktop_session"
        now = datetime.now(UTC)

        a11y_tree = {
            "role": "desktop_root",
            "name": self.active_window,
            "children": [
                {
                    "role": "window",
                    "title": self.active_window,
                    "bounds": [0, 0, self.screen_width, self.screen_height],
                    "controls": [
                        {"role": "button", "name": "Close", "id": "btn_close"},
                        {"role": "button", "name": "Minimize", "id": "btn_min"},
                    ],
                }
            ],
        }

        dom_json = (
            f'{{"active_window": "{self.active_window}", '
            f'"cursor": [{self.cursor_pos[0]}, {self.cursor_pos[1]}], '
            f'"open_windows": {self.open_windows}}}'
        )

        return Observation(
            observation_id=obs_id,
            task_id="active_task",
            session_id=session_id,
            timestamp=now,
            screenshot_ref=None,
            dom_snapshot=dom_json,
            accessibility_tree=a11y_tree,
            focused_element=f"window_{self.active_window.lower()}",
            window_title=self.active_window,
            metadata={
                "driver_type": "desktop",
                "screen_size": [self.screen_width, self.screen_height],
                "cursor_pos": list(self.cursor_pos),
                "open_windows": list(self.open_windows),
            },
        )

    async def execute(self, action: ComputerAction) -> ActionResult:
        """Execute a validated desktop computer action."""
        start_time = time.perf_counter()
        if not self.connected:
            raise RuntimeError("DesktopDriver is not connected. Call connect() first.")

        atype = action.action_type.lower()
        params = action.parameters or {}

        # Normalize action name
        if "_" in atype and "." not in atype:
            prefix, rest = atype.split("_", 1)
            atype = f"{prefix}.{rest}"

        if atype in ("desktop.click", "desktop.mouse_click"):
            x = int(params.get("x", self.cursor_pos[0]))
            y = int(params.get("y", self.cursor_pos[1]))
            # Bound to virtual screen dimensions
            x = max(0, min(self.screen_width, x))
            y = max(0, min(self.screen_height, y))
            self.cursor_pos = (x, y)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={"clicked_at": [x, y], "active_window": self.active_window},
                duration_ms=duration_ms,
                evidence={"cursor_pos": [x, y]},
            )

        elif atype in ("desktop.move_cursor", "desktop.mouse_move"):
            x = int(params.get("x", self.cursor_pos[0]))
            y = int(params.get("y", self.cursor_pos[1]))
            x = max(0, min(self.screen_width, x))
            y = max(0, min(self.screen_height, y))
            self.cursor_pos = (x, y)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={"cursor_pos": [x, y]},
                duration_ms=duration_ms,
                evidence={"cursor_pos": [x, y]},
            )

        elif atype in ("desktop.type", "desktop.keyboard_type"):
            text = str(params.get("text", ""))
            self.keyboard_buffer.append(text)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={"typed_length": len(text), "target_window": self.active_window},
                duration_ms=duration_ms,
                evidence={"buffer_size": len(self.keyboard_buffer)},
            )

        elif atype in ("desktop.press_key", "desktop.key_press"):
            key = str(params.get("key", "Enter"))
            self.keyboard_buffer.append(f"<{key}>")
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={"pressed_key": key},
                duration_ms=duration_ms,
                evidence={"pressed_key": key},
            )

        elif atype in ("desktop.focus_window", "desktop.switch_window"):
            window_title = str(params.get("title", params.get("window_id", self.default_window)))
            if window_title not in self.open_windows:
                self.open_windows.append(window_title)
            self.active_window = window_title
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={"active_window": self.active_window, "open_windows": self.open_windows},
                duration_ms=duration_ms,
                evidence={"active_window": self.active_window},
            )

        elif atype in ("desktop.launch_app", "desktop.open_app"):
            app_name = str(params.get("app_name", "Application"))
            if app_name not in self.open_windows:
                self.open_windows.append(app_name)
            self.active_window = app_name
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={"launched": app_name, "active_window": self.active_window},
                duration_ms=duration_ms,
                evidence={"launched": app_name},
            )

        elif atype in ("desktop.screenshot", "desktop.capture"):
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={
                    "captured": True,
                    "format": "png",
                    "width": self.screen_width,
                    "height": self.screen_height,
                },
                duration_ms=duration_ms,
                evidence={"screen_size": [self.screen_width, self.screen_height]},
            )

        else:
            raise ValueError(f"Unsupported desktop action type: '{action.action_type}'")

    async def health_check(self) -> DriverHealth:
        """Query desktop driver status and environment responsiveness."""
        return DriverHealth(
            status="ok" if self.connected else "disconnected",
            driver_type="desktop",
            connected=self.connected,
            details={
                "screen_size": [self.screen_width, self.screen_height],
                "cursor_pos": list(self.cursor_pos),
                "active_window": self.active_window,
                "open_windows": self.open_windows,
            },
        )

    async def disconnect(self) -> None:
        """Cleanly tear down desktop driver session."""
        self.connected = False
        self.active_window = self.default_window
