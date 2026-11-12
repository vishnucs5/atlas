"""Accessibility tree snapshot extractor."""

from typing import Any

from playwright.async_api import Page


async def extract_accessibility_tree(page: Page) -> dict[str, Any] | None:
    """Capture accessibility tree snapshot using CDP or DOM accessibility query.

    Returns hierarchical dictionary of accessibility nodes, or None if unsupported.
    """
    # 1. Try Chrome DevTools Protocol Accessibility domain if Chromium
    try:
        cdp_client = await page.context.new_cdp_session(page)
        ax_tree = await cdp_client.send("Accessibility.getFullAXTree")
        await cdp_client.detach()
        if isinstance(ax_tree, dict) and "nodes" in ax_tree:
            return {"source": "cdp", "nodes": ax_tree["nodes"][:100]}
    except Exception:
        pass

    # 2. Fallback: Extract semantic ARIA roles and labels directly from DOM
    try:
        aria_nodes = await page.evaluate(
            """() => {
                const results = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
                let node;
                while ((node = walker.nextNode()) && results.length < 100) {
                    const role = node.getAttribute('role') || node.tagName.toLowerCase();
                    const name = node.getAttribute('aria-label') || node.innerText || node.getAttribute('title') || '';
                    if (role && (name || ['input', 'button', 'select'].includes(node.tagName.toLowerCase()))) {
                        results.push({
                            role: role,
                            name: name.trim().slice(0, 80),
                            tag: node.tagName.toLowerCase()
                        });
                    }
                }
                return results;
            }"""
        )
        if aria_nodes:
            return {"source": "dom_aria", "nodes": aria_nodes}
    except Exception:
        pass

    return None
