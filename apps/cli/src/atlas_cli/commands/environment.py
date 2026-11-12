"""Environment diagnostic commands for ATLAS runtimes."""

import asyncio


async def _test_browser_async() -> int:
    print("Testing ATLAS Browser Runtime...")
    try:
        from atlas_browser.config import BrowserConfig
        from atlas_browser.driver import PlaywrightBrowserDriver

        driver = PlaywrightBrowserDriver(BrowserConfig(headless=True))
        await driver.connect()
        health = await driver.health_check()
        print(f"Driver Type: {health.driver_type}")
        print(f"Status:      {health.status}")
        print(f"Connected:   {health.connected}")
        print(f"Details:     {health.details}")
        await driver.disconnect()

        if health.status == "ok":
            print("Browser test: SUCCESS")
            return 0
        else:
            print(f"Browser test: DEGRADED ({health.details})")
            return 1
    except Exception as exc:
        print(f"Browser test: FAILED ({exc})")
        return 1


def run_environment_test_browser() -> int:
    """Run browser execution runtime health test."""
    return asyncio.run(_test_browser_async())
