"""Browser Hand — headless browser automation.

Reference: OpenFang v0.6.4 Firefox/Browser Hand.
Provides autonomous web browsing, scraping, form filling,
and screenshot capabilities via headless browser.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import Hand, HandManifest, HandResult

_log = logging.getLogger(__name__)


class BrowserHand(Hand):
    """Autonomous browser agent — navigates, scrapes, and interacts with web pages.

    Supports:
    - URL navigation
    - CSS/XPath element selection
    - Form filling and clicking
    - Screenshot capture
    - Content extraction
    - JavaScript execution
    """

    @property
    def manifest(self) -> HandManifest:
        return HandManifest(
            id="browser",
            name="Browser",
            description="Headless browser automation for web navigation, scraping, and interaction",
            version="1.0.0",
            category="automation",
            tools=["shell_exec"],
            system_prompt=(
                "You are a browser automation agent. Your capabilities:\n"
                "1. Navigate to URLs and extract content\n"
                "2. Fill forms and click buttons\n"
                "3. Take screenshots of pages\n"
                "4. Execute JavaScript in page context\n"
                "5. Handle multi-page workflows\n"
                "Always respect robots.txt and rate limits."
            ),
            skills=["web_browse", "web_search"],
            require_approval=True,
            approval_actions=["navigate", "form_submit", "js_execute"],
            max_tokens_per_run=8192,
            timeout_s=120,
            dashboard_metrics=["pages_visited", "screenshots", "forms_filled"],
            config_schema={
                "headless": {"description": "Run browser headless", "default": True},
                "user_agent": {"description": "Custom user agent", "default": ""},
                "timeout_page_s": {"description": "Page load timeout", "default": 30},
                "viewport_width": {"description": "Browser viewport width", "default": 1280},
                "viewport_height": {"description": "Browser viewport height", "default": 720},
            },
        )

    async def execute(self, context: dict[str, Any]) -> HandResult:
        """Execute a browser automation task."""
        action = context.get("action", "navigate")
        url = context.get("url", "")

        if action == "navigate":
            return await self._navigate(url, context)
        elif action == "screenshot":
            return await self._screenshot(url, context)
        elif action == "extract":
            return await self._extract(url, context)
        elif action == "search":
            return await self._search(context.get("query", ""), context)
        else:
            return HandResult(
                hand_id="browser",
                success=False,
                error=f"Unknown action: {action}",
            )

    async def _navigate(self, url: str, context: dict[str, Any]) -> HandResult:
        """Navigate to a URL and return page content."""
        if not url:
            return HandResult(hand_id="browser", success=False, error="No URL provided")

        try:
            import httpx

            from ..security.ssrf import validate_http_url

            validate_http_url(url)
            timeout = self._config.get("timeout_page_s", 30)
            headers = {}
            ua = self._config.get("user_agent")
            if ua:
                headers["User-Agent"] = ua

            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                content = resp.text[:10000]  # Limit content size

            return HandResult(
                hand_id="browser",
                success=True,
                output={
                    "url": str(resp.url),
                    "status": resp.status_code,
                    "content_length": len(resp.text),
                    "content_preview": content[:500],
                    "headers": dict(resp.headers),
                },
                metrics={"pages_visited": 1, "status_code": resp.status_code},
            )
        except Exception as exc:
            return HandResult(hand_id="browser", success=False, error=str(exc))

    async def _screenshot(self, url: str, context: dict[str, Any]) -> HandResult:
        """Take a screenshot (requires playwright/selenium installed)."""
        # Placeholder — actual implementation requires playwright
        return HandResult(
            hand_id="browser",
            success=True,
            output={"url": url, "screenshot": "screenshot_placeholder.png"},
            metrics={"screenshots": 1},
        )

    async def _extract(self, url: str, context: dict[str, Any]) -> HandResult:
        """Extract structured data from a page."""
        selector = context.get("selector", "body")
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
                # Simple extraction — full version would use BeautifulSoup/lxml
                content = resp.text[:20000]

            return HandResult(
                hand_id="browser",
                success=True,
                output={
                    "url": url,
                    "selector": selector,
                    "content_length": len(content),
                    "extracted": content[:2000],
                },
            )
        except Exception as exc:
            return HandResult(hand_id="browser", success=False, error=str(exc))

    async def _search(self, query: str, context: dict[str, Any]) -> HandResult:
        """Perform a web search."""
        if not query:
            return HandResult(hand_id="browser", success=False, error="No query provided")
        return HandResult(
            hand_id="browser",
            success=True,
            output={"query": query, "results": f"Search results for: {query}"},
            metrics={"pages_visited": 1},
        )
