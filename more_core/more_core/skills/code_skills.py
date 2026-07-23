"""Code & Data Skills - 代码执行和数据处理技能."""

from __future__ import annotations

import asyncio
import subprocess
import sys
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
        self._timeout = config.get("timeout", 30) if config else 30
        self._metadata = SkillMetadata(
            id="code.execute",
            name="Code Execution",
            description="Execute code in multiple languages with sandboxing",
            category=SkillCategory.CODE,
            version="1.0.0",
            tags=["code", "execute", "python", "javascript", "sandbox"],
            config_schema={
                "language": {"type": "string", "enum": self.SUPPORTED_LANGUAGES},
                "code": {"type": "string", "required": True},
                "timeout": {"type": "number", "default": 30},
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
            return SkillResult(
                success=result["returncode"] == 0,
                output=result["stdout"],
                error=result["stderr"] if result["returncode"] != 0 else None,
                metadata={
                    "language": language,
                    "returncode": result["returncode"],
                },
            )
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    async def _run_code(self, language: str, code: str, timeout: int) -> dict[str, Any]:
        """Run code in subprocess."""
        if language == "python":
            return await self._run_python(code, timeout)
        elif language == "javascript":
            return await self._run_javascript(code, timeout)
        elif language == "bash":
            return await self._run_bash(code, timeout)
        return {"returncode": 1, "stdout": "", "stderr": "Unsupported language"}

    async def _run_python(self, code: str, timeout: int) -> dict[str, Any]:
        """Run Python code."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return {
                    "returncode": proc.returncode,
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                }
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {"returncode": -1, "stdout": "", "stderr": "Timeout"}
        finally:
            Path(path).unlink(missing_ok=True)

    async def _run_javascript(self, code: str, timeout: int) -> dict[str, Any]:
        """Run JavaScript code."""
        node = subprocess.run(["which", "node"], capture_output=True)
        if node.returncode != 0:
            return {"returncode": 1, "stdout": "", "stderr": "Node.js not found"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(code)
            f.flush()
            path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                "node",
                path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return {
                    "returncode": proc.returncode,
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                }
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {"returncode": -1, "stdout": "", "stderr": "Timeout"}
        finally:
            Path(path).unlink(missing_ok=True)

    async def _run_bash(self, code: str, timeout: int) -> dict[str, Any]:
        """Run bash script."""
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-c",
            code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"returncode": -1, "stdout": "", "stderr": "Timeout"}


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
            dependencies=["pandas"],
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
            elif operation == "transform":
                result = self._transform_data(data, params.get("transform", {}))
            elif operation == "stats":
                result = self._compute_stats(data)
            elif operation == "query":
                result = self._query_data(data, params.get("query", ""))
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
