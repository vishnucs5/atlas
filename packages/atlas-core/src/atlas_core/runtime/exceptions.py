"""Driver-level domain exceptions for the ATLAS runtime."""


class DriverError(Exception):
    """Base exception for computer driver execution failures."""


class NavigationTimeoutError(DriverError):
    """Raised when page navigation fails to reach desired ready state within timeout."""


class ElementNotFoundError(DriverError):
    """Raised when an action target element cannot be located in the DOM."""


class DetachedElementError(DriverError):
    """Raised when an element reference detaches from DOM before action completion."""


class BrowserCrashError(DriverError):
    """Raised when the underlying browser engine process terminates unexpectedly."""


class ActionExecutionError(DriverError):
    """Raised when driver fails to execute an authorized action."""
