"""Network request, response, and error monitor for browser pages."""

from typing import Any

from playwright.async_api import ConsoleMessage, Page, Request, Response


class NetworkMonitor:
    """Monitors HTTP traffic, console messages, and page-level runtime errors."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.console_messages: list[dict[str, str]] = []

    def attach(self, page: Page) -> None:
        """Attach event listeners to the given Playwright page."""
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("pageerror", self._on_page_error)
        page.on("console", self._on_console)

    def _on_request(self, request: Request) -> None:
        self.requests.append(
            {
                "url": request.url,
                "method": request.method,
                "resource_type": request.resource_type,
            }
        )
        if len(self.requests) > 200:
            self.requests.pop(0)

    def _on_response(self, response: Response) -> None:
        self.responses.append(
            {
                "url": response.url,
                "status": response.status,
                "ok": response.ok,
            }
        )
        if len(self.responses) > 200:
            self.responses.pop(0)

    def _on_page_error(self, error: Exception) -> None:
        self.errors.append(str(error))
        if len(self.errors) > 50:
            self.errors.pop(0)

    def _on_console(self, msg: ConsoleMessage) -> None:
        self.console_messages.append({"type": msg.type, "text": msg.text[:200]})
        if len(self.console_messages) > 100:
            self.console_messages.pop(0)

    def get_summary(self) -> dict[str, Any]:
        """Return diagnostic summary of recent network and console activity."""
        failed_responses = [r for r in self.responses if not r["ok"]]
        return {
            "total_requests": len(self.requests),
            "total_responses": len(self.responses),
            "failed_responses_count": len(failed_responses),
            "recent_errors": self.errors[-5:] if self.errors else [],
            "recent_failed_responses": failed_responses[-5:] if failed_responses else [],
        }

    def clear(self) -> None:
        """Reset captured events."""
        self.requests.clear()
        self.responses.clear()
        self.errors.clear()
        self.console_messages.clear()
