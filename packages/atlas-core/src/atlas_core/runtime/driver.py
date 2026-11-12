"""ComputerDriver protocol definition for the ATLAS runtime."""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from atlas_core.contracts.action import ActionResult, ComputerAction
from atlas_core.contracts.observation import Observation


class DriverHealth(BaseModel):
    """Health check outcome for a computer driver."""

    model_config = ConfigDict(validate_assignment=True)

    status: str = "ok"
    driver_type: str
    connected: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ComputerDriver(Protocol):
    """Protocol defining low-level execution drivers (browser, desktop, terminal).

    In accordance with Constitution Rule 1:
    Drivers implement interfaces; they never own planning or planning state.
    """

    async def connect(self, config: dict[str, Any] | None = None) -> Any:
        """Establish or attach to the computer execution environment."""
        ...

    async def observe(self) -> Observation:
        """Capture the current multimodal or structured state of the environment."""
        ...

    async def execute(self, action: ComputerAction) -> ActionResult:
        """Execute a validated and authorized ComputerAction."""
        ...

    async def health_check(self) -> DriverHealth:
        """Query driver status and environment responsiveness."""
        ...

    async def disconnect(self) -> None:
        """Cleanly close and tear down the driver session and resources."""
        ...
