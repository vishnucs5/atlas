"""DriverRegistry for routing actions across multiple heterogeneous computer drivers."""

from typing import Any

from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.observation import Observation
from atlas_core.runtime.driver import ComputerDriver, DriverHealth


class DriverRegistry(ComputerDriver):
    """Registry and dispatcher for multiple computer drivers (browser, desktop, terminal).

    Allows registering drivers by prefix or domain (e.g. 'browser', 'desktop') and routes
    actions deterministically according to action_type. Also satisfies the ComputerDriver
    protocol itself, delegating execute() to the appropriate driver and observe() to the
    active/default driver.
    """

    def __init__(self, default_prefix: str | None = None) -> None:
        self._drivers: dict[str, ComputerDriver] = {}
        self._default_prefix: str | None = default_prefix
        self._active_prefix: str | None = default_prefix

    @property
    def drivers(self) -> dict[str, ComputerDriver]:
        """Dictionary of registered drivers keyed by prefix."""
        return dict(self._drivers)

    @property
    def default_driver(self) -> ComputerDriver | None:
        """The currently configured default driver."""
        if self._default_prefix and self._default_prefix in self._drivers:
            return self._drivers[self._default_prefix]
        return None

    @property
    def active_driver(self) -> ComputerDriver | None:
        """The driver currently designated for observation and general interaction."""
        if self._active_prefix and self._active_prefix in self._drivers:
            return self._drivers[self._active_prefix]
        return self.default_driver

    def register(
        self,
        prefix: str,
        driver: ComputerDriver,
        is_default: bool = False,
    ) -> None:
        """Register a driver under a specified prefix (e.g., 'browser', 'desktop')."""
        norm_prefix = prefix.strip().lower()
        self._drivers[norm_prefix] = driver
        if is_default or self._default_prefix is None:
            self._default_prefix = norm_prefix
            self._active_prefix = norm_prefix

    def unregister(self, prefix: str) -> ComputerDriver | None:
        """Unregister a driver by prefix."""
        norm_prefix = prefix.strip().lower()
        removed = self._drivers.pop(norm_prefix, None)
        if self._default_prefix == norm_prefix:
            self._default_prefix = next(iter(self._drivers)) if self._drivers else None
        if self._active_prefix == norm_prefix:
            self._active_prefix = self._default_prefix
        return removed

    def set_active_driver(self, prefix: str) -> None:
        """Set the active driver for observe() calls."""
        norm_prefix = prefix.strip().lower()
        if norm_prefix not in self._drivers:
            raise KeyError(f"Driver prefix '{prefix}' is not registered.")
        self._active_prefix = norm_prefix

    def resolve_driver(self, action_type: str) -> ComputerDriver:
        """Resolve the appropriate driver for a given action_type."""
        atype = action_type.strip().lower()

        # Check prefix separated by dot or underscore
        prefix: str | None = None
        if "." in atype:
            prefix = atype.split(".", 1)[0]
        elif "_" in atype:
            prefix = atype.split("_", 1)[0]

        if prefix and prefix in self._drivers:
            return self._drivers[prefix]

        # Direct match on entire action_type (rare)
        if atype in self._drivers:
            return self._drivers[atype]

        # Fall back to default driver if available
        if self.default_driver is not None:
            return self.default_driver

        raise ValueError(
            f"No driver registered for action '{action_type}' (prefix: '{prefix}') "
            f"and no default driver configured."
        )

    # -------------------------------------------------------------------------
    # ComputerDriver Protocol Implementation
    # -------------------------------------------------------------------------

    async def connect(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Connect all registered drivers with their respective configurations."""
        cfg = config or {}
        results: dict[str, Any] = {}
        for prefix, driver in self._drivers.items():
            driver_cfg = cfg.get(prefix, cfg)
            results[prefix] = await driver.connect(driver_cfg)
        return results

    async def observe(self) -> Observation:
        """Capture observation from the active (or default) driver."""
        driver = self.active_driver
        if not driver:
            raise RuntimeError("Cannot observe: No drivers registered in DriverRegistry.")
        return await driver.observe()

    async def execute(self, action: ComputerAction) -> ActionResult:
        """Route and execute an action on the resolved driver."""
        driver = self.resolve_driver(action.action_type)
        return await driver.execute(action)

    async def health_check(self) -> DriverHealth:
        """Aggregate health check results across all registered drivers."""
        if not self._drivers:
            return DriverHealth(
                status="warning",
                driver_type="registry",
                connected=False,
                details={"message": "No drivers registered"},
            )

        details: dict[str, Any] = {}
        all_ok = True
        any_connected = False

        for prefix, driver in self._drivers.items():
            try:
                health = await driver.health_check()
                details[prefix] = health.model_dump()
                if health.status != "ok":
                    all_ok = False
                if health.connected:
                    any_connected = True
            except Exception as exc:
                details[prefix] = {"status": "error", "error": str(exc)}
                all_ok = False

        status = "ok" if all_ok else ("degraded" if any_connected else "error")

        return DriverHealth(
            status=status,
            driver_type="registry",
            connected=any_connected,
            details=details,
        )

    async def disconnect(self) -> None:
        """Cleanly disconnect all registered drivers."""
        for driver in self._drivers.values():
            try:
                await driver.disconnect()
            except Exception:
                pass
