"""DOM inspection and structured interactive element extraction."""

from typing import Any

from playwright.async_api import Page

# JavaScript snippet executed in browser context to discover interactive elements
_INTERACTIVE_ELEMENTS_JS = """
() => {
    const isVisible = (elem) => {
        if (!elem) return false;
        const style = window.getComputedStyle(elem);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            return false;
        }
        const rect = elem.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };

    const selector = [
        'button',
        'a[href]',
        'input',
        'select',
        'textarea',
        '[role="button"]',
        '[role="link"]',
        '[role="checkbox"]',
        '[role="radio"]',
        '[role="menuitem"]',
        '[role="tab"]',
        '[tabindex]:not([tabindex="-1"])',
        '[onclick]'
    ].join(', ');

    const elements = Array.from(document.querySelectorAll(selector));
    return elements.filter(isVisible).slice(0, 150).map((el, index) => {
        const rect = el.getBoundingClientRect();
        const role = el.getAttribute('role') || el.tagName.toLowerCase();
        const ariaLabel = el.getAttribute('aria-label') || '';
        const name = el.getAttribute('name') || '';
        const id = el.id || '';
        const type = el.getAttribute('type') || '';
        const placeholder = el.getAttribute('placeholder') || '';
        const text = (el.innerText || el.value || '').trim().slice(0, 100);

        return {
            index: index,
            tag: el.tagName.toLowerCase(),
            role: role,
            name: name,
            id: id,
            type: type,
            placeholder: placeholder,
            aria_label: ariaLabel,
            text: text,
            bounds: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            }
        };
    });
}
"""


async def extract_dom_snapshot(page: Page, max_length: int = 50000) -> str:
    """Capture raw HTML content of the active page body, truncated to max_length."""
    try:
        content = await page.content()
        if len(content) > max_length:
            return content[:max_length] + "\n<!-- [DOM_SNAPSHOT_TRUNCATED] -->"
        return content
    except Exception as exc:
        return f"<!-- Failed to capture DOM snapshot: {exc} -->"


async def extract_interactive_elements(page: Page) -> list[dict[str, Any]]:
    """Query and return visible interactive elements in page context."""
    try:
        result = await page.evaluate(_INTERACTIVE_ELEMENTS_JS)
        if isinstance(result, list):
            return result
        return []
    except Exception:
        return []
