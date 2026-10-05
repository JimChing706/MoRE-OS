"""Code & Data Skills - 代码执行和数据处理技能."""

from __future__ import annotations

import tempfile
import json
import httpx
from pathlib import Path
from typing import Any, cast

from .base import Skill, SkillMetadata, SkillResult, SkillCategory


class CodeExecutionSkill(Skill):
    """代码执行技能 - 支持 Python/JavaScript."""

    SUPPORTED_LANGUAGES = ["python", "javascript", "bash"]

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        cfg = config or {}
        self._timeout = cfg.get("timeout", 30)
        # R-1 修复：代码一律在 OS 级安全沙箱内执行（AST 扫描 + argv 策略 +
        # 路径白名单 + 环境脱敏 + 超时 + 审计）。注入式 sandbox 便于测试/共享。
        import os as _os

        self._security_level = str(
            cfg.get("security_level") or _os.getenv("MORE_SANDBOX_LEVEL", "basic")
        )
        self._sandbox = cfg.get("sandbox") or self._build_sandbox(self._timeout)
        self._metadata = SkillMetadata(
            id="code.execute",
            name="Code Execution",
            # R-1 已修复：一律在 SecureSandbox 内执行（AST 扫描 + argv 策略 +
            # 路径白名单 + 环境脱敏 + 超时 + 审计）。
            description=(
                "Execute code in multiple languages inside the OS-level secure sandbox "
                "(python/javascript/bash)"
            ),
            category=SkillCategory.CODE,
            version="1.0.0",
            tags=["code", "execute", "python", "javascript", "sandbox"],
            config_schema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string", "minLength": 1, "maxLength": 200000,
                        "description": "待执行的源码",
                    },
                    "language": {
                        "type": "string", "enum": self.SUPPORTED_LANGUAGES,
                        "default": "python", "description": "源码语言",
                    },
                    "timeout": {
                        "type": "number", "minimum": 1, "maximum": 300, "default": 30,
                        "description": "执行超时秒数 (1-300)",
                    },
                },
                "required": ["code"],
                "additionalProperties": False,
            },
            maintainer="MoRE OS Core Team",
            deployment={
                "runtime": "python>=3.10",
                "packages": [],
                "network_egress": False,
                "sandbox_required": True,
                "runtimes": ["python3", "node", "bash"],
                "env": ["MORE_SANDBOX_LEVEL"],
            },
        )

    @property
    def metadata(self) -> SkillMetadata:
        return cast(SkillMetadata, self._metadata)

    async def validate(self, params: dict[str, Any]) -> tuple[bool, str]:
        if "code" not in params:
            return False, "Missing required parameter: code"
        lang = params.get("language", "python")
        if lang not in self.SUPPORTED_LANGUAGES:
            return False, f"Unsupported language: {lang}"
        return True, ""

    async def execute(self, params: dict[str, Any]) -> SkillResult:
        code = params.get("code", "")
        language = params.get("language", "python")
        timeout = params.get("timeout", self._timeout)

        try:
            result = await self._run_code(language, code, timeout)
            ok = result["returncode"] == 0 and not result.get("timed_out")
            return SkillResult(
                success=ok,
                output=result["stdout"],
                error=result["stderr"] if not ok else None,
                metadata={
                    "language": language,
                    "returncode": result["returncode"],
                    "sandboxed": result.get("sandboxed", True),
                    "sandbox_level": result.get("sandbox_level", self._security_level),
                    "timed_out": result.get("timed_out", False),
                },
            )
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    def _build_sandbox(self, timeout: int | float) -> Any:
        """按安全级别构建 OS 级沙箱（超时可覆盖）。"""
        from ..sandbox.secure_sandbox import create_secure_sandbox

        return create_secure_sandbox(
            security_level=self._security_level, timeout_s=int(timeout)
        )

    def _sandbox_for(self, timeout: int | float) -> Any:
        if int(timeout) == int(self._timeout):
            return self._sandbox
        return self._build_sandbox(timeout)

    async def _run_code(self, language: str, code: str, timeout: int) -> dict[str, Any]:
        """在安全沙箱内执行代码（R-1）。返回与旧实现兼容的 dict。"""
        sbx = self._sandbox_for(timeout)
        result = None
        if language == "python":
            result = await sbx.run_python(code)
        elif language == "javascript":
            result = await self._run_script(sbx, code, ".js", "node")
        elif language == "bash":
            result = await self._run_script(sbx, code, ".sh", "bash")
        if result is None:
            return {"returncode": 1, "stdout": "", "stderr": "Unsupported language",
                    "timed_out": False, "sandboxed": True}
        return {
            "returncode": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": bool(getattr(result, "timed_out", False)),
            "sandboxed": True,
            "sandbox_level": self._security_level,
        }

    @staticmethod
    async def _run_script(sbx: Any, code: str, suffix: str, interpreter: str) -> Any:
        """把脚本写入临时文件后经沙箱执行（避免 `bash -c` 被策略拦截）。"""
        with tempfile.TemporaryDirectory(prefix="more_skill_") as tmp:
            path = Path(tmp) / f"main{suffix}"
            path.write_text(code, encoding="utf-8")
            return await sbx.run([interpreter, str(path)])


class DataAnalysisSkill(Skill):
    """数据分析技能 - JSON/CSV 处理和统计分析."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._metadata = SkillMetadata(
            id="data.analyze",
            name="Data Analysis",
            description="Analyze and transform data (JSON, CSV, statistics)",
            category=SkillCategory.DATA,
            version="1.0.0",
            tags=["data", "analysis", "json", "csv", "statistics"],
            dependencies=[],  # 实现仅用标准库(json/csv)；此前误声明 pandas
            config_schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["parse", "transform", "stats", "query"],
                        "default": "parse", "description": "分析操作",
                    },
                    "data": {
                        "type": "string", "minLength": 1, "maxLength": 1000000,
                        "description": "待分析的数据文本 (JSON/CSV)",
                    },
                    "format": {
                        "type": "string", "enum": ["auto", "json", "csv"],
                        "default": "auto", "description": "数据格式",
                    },
                    "transform": {
                        "type": "object", "description": "转换规则 (operation=transform 时使用)",
                    },
                    "query": {
                        "type": "string", "maxLength": 2000,
                        "description": "查询表达式 (operation=query 时使用)",
                    },
                },
                "required": ["data"],
                "additionalProperties": False,
            },
            maintainer="MoRE OS Core Team",
            deployment={
                "runtime": "python>=3.10",
                "packages": ["pandas"],
                "network_egress": False,
                "sandbox_required": False,
                "env": [],
            },
        )

    @property
    def metadata(self) -> SkillMetadata:
        return cast(SkillMetadata, self._metadata)

    async def validate(self, params: dict[str, Any]) -> tuple[bool, str]:
        if "data" not in params and "operation" not in params:
            return False, "Missing required parameters"
        return True, ""

    async def execute(self, params: dict[str, Any]) -> SkillResult:
        operation = params.get("operation", "parse")
        data = params.get("data", "")

        try:
            if operation == "parse":
                result = self._parse_data(data, params.get("format", "auto"))
            else:
                # 先解析：transform/stats/query 需要结构化数据，此前直接把原始字符串
                # 传进去，导致 stats 恒返回 {'type': 'str'}、query 原样返回（缺陷修复）。
                parsed = self._parse_data(data, params.get("format", "auto")).get("parsed")
                if operation == "transform":
                    result = self._transform_data(parsed, params.get("transform", {}))
                elif operation == "stats":
                    result = self._compute_stats(parsed)
                elif operation == "query":
                    result = self._query_data(parsed, params.get("query", ""))
                else:
                    return SkillResult(success=False, error=f"Unknown operation: {operation}")

            return SkillResult(success=True, output=result, metadata={"operation": operation})
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    def _parse_data(self, data: str, format: str) -> dict[str, Any]:
        """Parse data from string."""
        if format == "json" or format == "auto":
            try:
                return {"parsed": json.loads(data), "format": "json"}
            except (json.JSONDecodeError, ValueError):
                pass

        if format == "csv" or format == "auto":
            lines = data.strip().split("\n")
            if len(lines) > 1:
                headers = lines[0].split(",")
                rows = [line.split(",") for line in lines[1:] if line.strip()]
                return {"parsed": {"headers": headers, "rows": rows}, "format": "csv"}

        return {"parsed": data, "format": "raw"}

    def _transform_data(self, data: Any, transform: dict[str, Any]) -> Any:
        """Transform data based on rules."""
        op = transform.get("op", "filter")

        if isinstance(data, dict):
            if op == "filter":
                return {k: v for k, v in data.items() if k in transform.get("keys", [])}
            elif op == "map":
                return {transform.get("key", k): v for k, v in data.items()}

        return data

    def _compute_stats(self, data: Any) -> dict[str, Any]:
        """Compute basic statistics."""
        if isinstance(data, list):
            numeric = [x for x in data if isinstance(x, (int, float))]
            if numeric:
                return {
                    "count": len(data),
                    "numeric_count": len(numeric),
                    "sum": sum(numeric),
                    "mean": sum(numeric) / len(numeric),
                    "min": min(numeric),
                    "max": max(numeric),
                }
            return {"count": len(data), "unique": len(set(data))}
        elif isinstance(data, dict):
            return {"keys": list(data.keys()), "count": len(data)}
        return {"type": type(data).__name__}

    def _query_data(self, data: Any, query: str) -> Any:
        """Simple query on data."""
        if not query:
            return data

        if isinstance(data, list):
            return [x for x in data if query.lower() in str(x).lower()][:10]
        return data


class APICallSkill(Skill):
    """API 调用技能 - 统一的 HTTP 请求处理."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._metadata = SkillMetadata(
            id="api.call",
            name="API Call",
            description="Make HTTP API calls with authentication and retry",
            category=SkillCategory.API,
            version="1.0.0",
            tags=["api", "http", "request", "rest"],
            dependencies=["httpx"],
            config_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string", "format": "uri", "pattern": "^https?://",
                        "minLength": 1, "maxLength": 2048,
                        "description": "目标 API URL (http/https)",
                    },
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                        "default": "GET", "description": "HTTP 方法",
                    },
                    "headers": {"type": "object", "description": "请求头"},
                    "body": {"description": "请求体（POST/PUT/PATCH 时发送）"},
                    "timeout": {
                        "type": "number", "minimum": 1, "maximum": 300, "default": 30,
                        "description": "请求超时秒数 (1-300)",
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
        method = params.get("method", "GET").upper()
        headers = params.get("headers", {})
        body = params.get("body")
        timeout = params.get("timeout", 30)

        try:
            # SSRF 防护（与 web.browse 保持一致）：拒绝非 http(s)、缺主机、
            # 以及私网/回环/链路本地地址（防打内网、云元数据 169.254.169.254）。
            from ..security.ssrf import validate_http_url

            validate_http_url(url)

            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=body if body and method in ("POST", "PUT", "PATCH") else None,
                )

                try:
                    response_data = r.json()
                except ValueError:
                    response_data = r.text[:5000]

                return SkillResult(
                    success=r.status_code < 400,
                    output=response_data,
                    error=f"HTTP {r.status_code}" if r.status_code >= 400 else None,
                    metadata={
                        "status_code": r.status_code,
                        "headers": dict(r.headers),
                    },
                )
        except Exception as e:
            return SkillResult(success=False, error=str(e))
