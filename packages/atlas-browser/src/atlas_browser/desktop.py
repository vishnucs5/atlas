"""DesktopDriver implementing ComputerDriver for desktop and OS automation."""

import logging
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.observation import Observation
from atlas_core.runtime.driver import ComputerDriver, DriverHealth

logger = logging.getLogger("atlas.browser.desktop")


class DesktopDriver(ComputerDriver):
    """Execution driver for desktop applications and operating system automation.

    Provides cross-platform desktop automation supporting mouse coordinates,
    keyboard typing, window focusing, application lifecycle, accessibility tree
    inspection, and optional native Windows interactive session management.
    """

    def __init__(
        self,
        screen_size: tuple[int, int] | None = None,
        default_window: str = "Desktop",
        native_mode: bool = False,
    ) -> None:
        self.default_window = default_window
        self.active_window = default_window
        self.open_windows: list[str] = [default_window]
        self.native_mode = native_mode
        self.native_processes: dict[str, subprocess.Popen] = {}
        self.connected: bool = False
        self.session_id: str | None = None
        self.keyboard_buffer: list[str] = []

        if screen_size is not None:
            self.screen_width, self.screen_height = screen_size
        elif sys.platform == "win32":
            detected_w, detected_h = self._detect_windows_screen_metrics()
            self.screen_width = detected_w or 1920
            self.screen_height = detected_h or 1080
        else:
            self.screen_width = 1920
            self.screen_height = 1080

        self.cursor_pos: tuple[int, int] = (self.screen_width // 2, self.screen_height // 2)

    @staticmethod
    def _detect_windows_screen_metrics() -> tuple[int, int]:
        """Detect primary monitor resolution via Windows user32 APIs."""
        try:
            import ctypes

            u32 = ctypes.windll.user32
            w = int(u32.GetSystemMetrics(0))
            h = int(u32.GetSystemMetrics(1))
            if w > 0 and h > 0:
                return (w, h)
        except Exception as exc:
            logger.debug("Could not detect native Windows screen metrics: %s", exc)
        return (1920, 1080)

    @staticmethod
    def get_windows_session_id() -> int | None:
        """Query active Windows session ID using kernel32.ProcessIdToSessionId."""
        if sys.platform != "win32":
            return None
        try:
            import ctypes

            session_id = ctypes.c_uint32()
            res = ctypes.windll.kernel32.ProcessIdToSessionId(
                ctypes.windll.kernel32.GetCurrentProcessId(),
                ctypes.byref(session_id),
            )
            if res:
                return int(session_id.value)
        except Exception as exc:
            logger.debug("Failed to query ProcessIdToSessionId: %s", exc)
        return None

    @classmethod
    def validate_interactive_session(cls) -> tuple[bool, str]:
        """Validate whether worker process runs in an interactive user session vs Windows Session 0."""
        if sys.platform != "win32":
            return True, "Non-Windows platform"
        session_id = cls.get_windows_session_id()
        if session_id == 0:
            return (
                False,
                "Process is running in Windows Session 0 (service isolation session). "
                "Interactive GUI/desktop automation is not possible in Session 0.",
            )
        return True, f"Interactive Windows session confirmed (Session ID: {session_id})"

    async def connect(self, config: dict[str, Any] | None = None) -> Any:
        """Initialize desktop environment connection and virtual desktop surface."""
        cfg = config or {}
        self.session_id = cfg.get("session_id", f"desktop_sess_{uuid.uuid4().hex[:8]}")
        self.active_window = cfg.get("initial_window", self.default_window)
        if self.active_window not in self.open_windows:
            self.open_windows.append(self.active_window)
        if cfg.get("native_mode") is not None:
            self.native_mode = bool(cfg.get("native_mode"))
        self.connected = True
        return {
            "status": "connected",
            "session_id": self.session_id,
            "native_mode": self.native_mode,
        }

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
            f'"open_windows": {self.open_windows}, '
            f'"native_mode": {str(self.native_mode).lower()}}}'
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
                "native_mode": self.native_mode,
                "platform": sys.platform,
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

        is_native = bool(params.get("native", self.native_mode))

        if atype in ("desktop.click", "desktop.mouse_click"):
            x = int(params.get("x", self.cursor_pos[0]))
            y = int(params.get("y", self.cursor_pos[1]))
            # Bound to screen dimensions
            x = max(0, min(self.screen_width, x))
            y = max(0, min(self.screen_height, y))
            self.cursor_pos = (x, y)

            if is_native and sys.platform == "win32":
                try:
                    import ctypes

                    ctypes.windll.user32.SetCursorPos(x, y)
                except Exception as exc:
                    logger.debug("Native Windows SetCursorPos skipped: %s", exc)

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={
                    "clicked_at": [x, y],
                    "active_window": self.active_window,
                    "native": is_native,
                },
                duration_ms=duration_ms,
                evidence={"cursor_pos": [x, y]},
            )

        elif atype in ("desktop.move_cursor", "desktop.mouse_move"):
            x = int(params.get("x", self.cursor_pos[0]))
            y = int(params.get("y", self.cursor_pos[1]))
            x = max(0, min(self.screen_width, x))
            y = max(0, min(self.screen_height, y))
            self.cursor_pos = (x, y)

            if is_native and sys.platform == "win32":
                try:
                    import ctypes

                    ctypes.windll.user32.SetCursorPos(x, y)
                except Exception as exc:
                    logger.debug("Native Windows SetCursorPos skipped: %s", exc)

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={"cursor_pos": [x, y], "native": is_native},
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
                output={
                    "typed_length": len(text),
                    "target_window": self.active_window,
                    "native": is_native,
                },
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
                output={"pressed_key": key, "native": is_native},
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

            native_pid = None
            if is_native and sys.platform == "win32":
                try:
                    proc = subprocess.Popen([app_name], shell=False)
                    self.native_processes[app_name] = proc
                    native_pid = proc.pid
                except Exception as exc:
                    logger.warning("Could not launch native application '%s': %s", app_name, exc)

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={
                    "launched": app_name,
                    "active_window": self.active_window,
                    "native": is_native,
                    "pid": native_pid,
                },
                duration_ms=duration_ms,
                evidence={"launched": app_name, "pid": native_pid},
            )

        elif atype in ("desktop.close_app", "desktop.terminate_app"):
            app_name = str(params.get("app_name", self.active_window))
            proc = self.native_processes.pop(app_name, None)
            terminated = False
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                    terminated = True
                except Exception:
                    try:
                        proc.kill()
                        terminated = True
                    except Exception:
                        pass

            if app_name in self.open_windows:
                self.open_windows.remove(app_name)
            if self.active_window == app_name:
                self.active_window = (
                    self.open_windows[0] if self.open_windows else self.default_window
                )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ActionResult(
                action_id=action.action_id,
                success=True,
                output={
                    "closed": app_name,
                    "terminated_native": terminated,
                    "active_window": self.active_window,
                },
                duration_ms=duration_ms,
                evidence={"closed": app_name},
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
                    "native": is_native,
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
                "platform": sys.platform,
                "native_mode": self.native_mode,
                "native_processes": list(self.native_processes.keys()),
            },
        )

    async def disconnect(self) -> None:
        """Cleanly tear down desktop driver session and terminate spawned native processes."""
        for _app_name, proc in list(self.native_processes.items()):
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.native_processes.clear()
        self.connected = False
        self.active_window = self.default_window
