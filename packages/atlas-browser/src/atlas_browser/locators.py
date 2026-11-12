"""Resilient locator resolution for browser action targets."""

from typing import Any

from atlas_core.contracts.action import ActionTarget
from atlas_core.runtime.exceptions import ElementNotFoundError
from playwright.async_api import Locator, Page


def resolve_locator(page: Page, target: ActionTarget) -> Locator:
    """Resolve an ActionTarget specification into a Playwright Locator.

    Supports:
    - 'accessible_role' / 'role': page.get_by_role(role, name=...)
    - 'text': page.get_by_text(text, exact=...)
    - 'placeholder': page.get_by_placeholder(text)
    - 'label': page.get_by_label(text)
    - 'test_id': page.get_by_test_id(test_id)
    - 'css' / 'selector': page.locator(selector)
    - 'xpath': page.locator(f"xpath={selector}")
    """
    strategy = target.strategy.lower()
    params = target.parameters

    val = target.value or params.get("value")

    if strategy in ("accessible_role", "role"):
        role = params.get("role", "button")
        name = params.get("name") or val
        exact = params.get("exact", False)
        if name:
            return page.get_by_role(role, name=str(name), exact=exact)
        return page.get_by_role(role)

    elif strategy == "text":
        text = params.get("text") or val or ""
        exact = params.get("exact", False)
        return page.get_by_text(str(text), exact=exact)

    elif strategy == "placeholder":
        text = params.get("text") or params.get("placeholder") or val or ""
        return page.get_by_placeholder(str(text))

    elif strategy == "label":
        text = params.get("text") or params.get("label") or val or ""
        return page.get_by_label(str(text))

    elif strategy in ("test_id", "testid"):
        test_id = params.get("test_id") or params.get("id") or val or ""
        return page.get_by_test_id(str(test_id))

    elif strategy in ("css", "selector"):
        selector = params.get("selector") or params.get("css") or val
        if not selector:
            raise ElementNotFoundError("CSS locator requires 'selector' parameter")
        return page.locator(str(selector))

    elif strategy == "xpath":
        xpath = params.get("xpath") or params.get("selector") or val
        if not xpath:
            raise ElementNotFoundError("XPath locator requires 'xpath' parameter")
        return page.locator(f"xpath={xpath}")

    else:
        # Default fallback to css locator if parameter 'selector' or val exists
        fallback_selector = params.get("selector") or val
        if fallback_selector:
            return page.locator(str(fallback_selector))
        raise ElementNotFoundError(f"Unsupported locator strategy: '{strategy}'")


def resolve_coordinates(
    target: ActionTarget | None, params: dict[str, Any]
) -> tuple[int, int] | None:
    """Extract coordinates (x, y) if target or params specify coordinate strategy."""
    if target and target.strategy.lower() in ("coordinates", "coord", "xy"):
        x = target.parameters.get("x")
        y = target.parameters.get("y")
        if x is not None and y is not None:
            return int(x), int(y)

    if "x" in params and "y" in params:
        return int(params["x"]), int(params["y"])

    return None
