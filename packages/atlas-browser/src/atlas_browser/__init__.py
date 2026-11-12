"""Playwright browser driver and execution runtime for ATLAS."""

from atlas_browser.actions import BrowserActionExecutor
from atlas_browser.config import BrowserConfig
from atlas_browser.desktop import DesktopDriver
from atlas_browser.downloads import DownloadManager
from atlas_browser.driver import PlaywrightBrowserDriver
from atlas_browser.locators import resolve_coordinates, resolve_locator
from atlas_browser.network import NetworkMonitor
from atlas_browser.registry import DriverRegistry

__all__ = [
    "BrowserActionExecutor",
    "BrowserConfig",
    "DesktopDriver",
    "DownloadManager",
    "DriverRegistry",
    "NetworkMonitor",
    "PlaywrightBrowserDriver",
    "resolve_coordinates",
    "resolve_locator",
]
