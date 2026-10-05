"""Web Skills - 网页搜索和浏览技能."""

from __future__ import annotations

import json
from typing import Any, cast

import httpx

from .base import Skill, SkillMetadata, SkillResult, SkillCategory


class WebSearchSkill(Skill):
    """网页搜索技能 - 支持多种搜索API."""

    DEFAULT_PROVIDERS = ["duckduckgo", "serpapi", "brave"]

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._providers = (
            config.get("providers", self.DEFAULT_PROVIDERS) if config else self.DEFAULT_PROVIDERS
        )
        self._session: httpx.AsyncClient | None = None
        self._metadata = SkillMetadata(
            id="web.search",
            name="Web Search",
            description="Search the web for information using multiple providers",
            category=SkillCategory.WEB,
            version="1.0.0",
            tags=["search", "web", "information", "research"],
            dependencies=["httpx"],
            config_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string", "minLength": 1, "maxLength": 2000,
                        "description": "搜索关键词",
                    },
                    "limit": {
                        "type": "integer", "minimum": 1, "maximum": 50, "default": 10,
                        "description": "返回结果条数 (1-50)",
                    },
                    "provider": {
                        "type": "string", "enum": ["duckduckgo", "serpapi"],
                        "default": "duckduckgo", "description": "搜索提供方",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            maintainer="MoRE OS Core Team",
            deployment={
                "runtime": "python>=3.10",
                "packages": ["httpx"],
                "network_egress": True,
                "network_targets": ["html.duckduckgo.com:443", "serpapi.com:443"],
                "sandbox_required": False,
                "env": [],
            },
        )

    @property
    def metadata(self) -> SkillMetadata:
        return cast(SkillMetadata, self._metadata)

    async def validate(self, params: dict[str, Any]) -> tuple[bool, str]:
        if "query" not in params:
            return False, "Missing required parameter: query"
        return True, ""

    async def execute(self, params: dict[str, Any]) -> SkillResult:
        query = params.get("query", "")
        limit = params.get("limit", 10)
        provider = params.get("provider", "duckduckgo")

        try:
            results = await self._search(provider, query, limit)
            return SkillResult(
                success=True,
                output=results,
                metadata={
                    "provider": provider,
                    # 显式声明"实际使用"的来源；不再静默换源（R-2）
                    "provider_used": provider,
                    "query": query,
                },
            )
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    def _serpapi_key(self) -> str:
        """SerpAPI key 来源：技能 config 优先，其次环境变量 SERPAPI_API_KEY。"""
        import os

        return str(
            self._config.get("serpapi_key") or os.getenv("SERPAPI_API_KEY") or ""
        ).strip()

    async def _search(self, provider: str, query: str, limit: int) -> list[dict[str, Any]]:
        """按指定 provider 搜索。

        R-2 修复：此前 serpapi 缺 key、或 provider 未知时会**静默降级**为
        DuckDuckGo，而 metadata 仍报告原 provider —— 调用方"以为用了 A，实际用了 B"。
        现在改为**显式报错**，让调用方明确知道该换源还是配置 key。
        """
        if provider == "duckduckgo":
            return await self._search_duckduckgo(query, limit)
        if provider == "serpapi":
            if not self._serpapi_key():
                raise ValueError(
                    "provider 'serpapi' 需要 API key：请配置技能 config.serpapi_key "
                    "或环境变量 SERPAPI_API_KEY（已不再静默降级为 duckduckgo）"
                )
            return await self._search_serpapi(query, limit)
        raise ValueError(f"未知搜索 provider: {provider!r}（可选: duckduckgo, serpapi）")

    async def _search_duckduckgo(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Search via DuckDuckGo HTML."""
        url = "https://html.duckduckgo.com/html/"
        data = {"q": query, "b": "", "kl": "us-en"}

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, data=data)
            html = r.text

            results = []
            import re

            pattern = r'<a class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>.*?<a class="result__snippet"[^>]*>([^<]+)</a>'
            for match in re.findall(pattern, html, re.DOTALL)[:limit]:
                results.append(
                    {
                        "title": match[1].strip(),
                        "url": match[0],
                        "snippet": match[2].strip(),
                    }
                )
            return results

    async def _search_serpapi(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Search via SerpAPI (requires key)."""
        api_key = self._serpapi_key()
        if not api_key:
            raise ValueError("serpapi_key 未配置（config.serpapi_key 或 SERPAPI_API_KEY）")

        url = f"https://serpapi.com/search.json?q={query}&api_key={api_key}&num={limit}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            data = r.json()
            return [
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
                for item in data.get("organic_results", [])[:limit]
            ]

    async def start(self) -> None:
        self._session = httpx.AsyncClient()
        await super().start()

    async def stop(self) -> None:
        if self._session:
            await self._session.aclose()
        await super().stop()


class WebBrowseSkill(Skill):
    """网页浏览技能 - 获取和解析网页内容."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._metadata = SkillMetadata(
            id="web.browse",
            name="Web Browse",
            description="Fetch and parse web page content",
            category=SkillCategory.WEB,
            version="1.0.0",
            tags=["browse", "scrape", "web", "html"],
            dependencies=["httpx"],  # 实现用正则解析 HTML；此前误声明 beautifulsoup4
            config_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string", "format": "uri", "pattern": "^https?://",
                        "minLength": 1, "maxLength": 2048,
                        "description": "目标网页 URL，必须以 http:// 或 https:// 开头",
                    },
                    "extract": {
                        "type": "string", "enum": ["text", "json", "links"],
                        "default": "text", "description": "内容抽取类型",
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            maintainer="MoRE OS Core Team",
            deployment={
                "runtime": "python>=3.10",
                "packages": ["httpx"],
                "network_egress": True,
                "network_targets": ["example.com:443"],
                "sandbox_required": False,
                "env": [],
            },
        )

    @property
    def metadata(self) -> SkillMetadata:
        return cast(SkillMetadata, self._metadata)

    async def validate(self, params: dict[str, Any]) -> tuple[bool, str]:
        if "url" not in params:
            return False, "Missing required parameter: url"
        return True, ""

    async def execute(self, params: dict[str, Any]) -> SkillResult:
        url = params.get("url", "")
        extract_type = params.get("extract", "text")

        try:
            from ..security.ssrf import validate_http_url

            validate_http_url(url)
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get(url)
                r.raise_for_status()

                content: Any
                if extract_type == "text":
                    content = self._extract_text(r.text)
                elif extract_type == "json":
                    content = self._extract_json(r.text)
                elif extract_type == "links":
                    content = self._extract_links(r.text)
                else:
                    content = r.text[:10000]

                return SkillResult(
                    success=True,
                    output={"url": url, "content": content, "status": r.status_code},
                    metadata={"extract_type": extract_type},
                )
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    def _extract_text(self, html: str) -> str:
        """Extract clean text from HTML."""
        import re

        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()[:5000]

    def _extract_json(self, html: str) -> dict[str, Any]:
        """Try to extract JSON from HTML."""
        import re

        json_match = re.search(r"\{.*\}", html, re.DOTALL)
        if json_match:
            try:
                return cast(dict[str, Any], json.loads(json_match.group()))
            except (json.JSONDecodeError, ValueError):
                pass
        return {"raw_length": len(html)}

    def _extract_links(self, html: str) -> list[dict[str, Any]]:
        import re

        pattern = r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>'
        return [{"url": m[0], "text": m[1].strip()} for m in re.findall(pattern, html)[:20]]
