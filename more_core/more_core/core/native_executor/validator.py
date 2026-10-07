"""原生执行器 - 验证模块 (Validator)。

职责：
  - 运行 4 条标准命令校验构建产物：
      1) cargo build --release -q
      2) cargo test  --release -q
      3) tar tzf <tar.gz>  （校验 tar.gz 归档完整性）
      4) unzip -l    <zip>      （校验 zip 归档完整性）
  - 每条命令最多重试 retries=3 次（指数退避 0.1s / 0.2s / 0.4s）。
  - 返回 ValidationResult（整体 pass + 每条命令的 stdout/stderr 列表）。

零新增第三方依赖，仅使用标准库 subprocess / time / dataclasses。
"""

from __future__ import annotations

import subprocess
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from .types import AggregatedValidationResult, ValidationBlockingLevel


@dataclass
class CommandRun:
    """单次命令执行的详细结果。"""

    cmd: list[str]
    cwd: str
    attempt: int  # 第几次尝试（从 1 开始）
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int


@dataclass
class ValidationResult:
    """Validator.validate() 返回的结构化结果。"""

    pass_: bool
    command_results: list[CommandRun] = field(default_factory=list)

    @property
    def total_commands(self) -> int:
        return len(self.command_results)

    @property
    def passed_commands(self) -> int:
        return sum(1 for r in self.command_results if r.returncode == 0)

    def stdout_of(self, index: int) -> str:
        """按索引获取某条命令的 stdout（空保护）。"""
        if 0 <= index < len(self.command_results):
            return self.command_results[index].stdout
        return ""

    def stderr_of(self, index: int) -> str:
        """按索引获取某条命令的 stderr（空保护）。"""
        if 0 <= index < len(self.command_results):
            return self.command_results[index].stderr
        return ""


class Validator:
    """构建产物验证器。

    典型用法::

        from more_core.core.native_executor.validator import Validator
        validator = Validator()
        result = validator.validate(project_root, artifacts)
        print("pass:", result.pass_)
    """

    DEFAULT_CMDS: tuple[tuple[str, ...], ...] = (
        ("cargo", "build", "--release", "-q"),
        ("cargo", "test", "--release", "-q"),
    )

    def __init__(
        self,
        *,
        retries: int = 3,
        initial_backoff_s: float = 0.1,
        timeout_s: Optional[int] = 600,
        _run_hook=None,
    ) -> None:
        """初始化 Validator。

        Args:
            retries:            每条命令最大尝试次数，默认 3。
            initial_backoff_s:  首次重试前等待秒数（后续每次 ×2 指数退避）。
            timeout_s:          单次 subprocess 超时（秒），默认 10 分钟。
            _run_hook:          单测注入：替换 _run_once 的实现，签名与 _run_once 相同。
        """
        self.retries = max(1, int(retries))
        self.initial_backoff_s = max(0.0, float(initial_backoff_s))
        self.timeout_s = timeout_s
        self._run_hook = _run_hook

    # ------------------------------------------------------------
    # 公开 API：两阶段 Validator + 聚合
    # ------------------------------------------------------------

    def validate_source(self, project_root: str) -> ValidationResult:
        """Phase 3A（Writer 之后、Delivery 之前跑）：cargo build + cargo test。

        基础格式、参数合法性的前置校验（第一阶段）。
        """
        result = ValidationResult(pass_=True)
        project_root_abs = str(Path(project_root).resolve())
        for cmd_tuple in self.DEFAULT_CMDS:
            run = self._run_with_retries(list(cmd_tuple), cwd=project_root_abs)
            result.command_results.append(run)
            if run.returncode != 0:
                result.pass_ = False
        return result

    def validate_archives(self, artifacts: dict[str, str]) -> ValidationResult:
        """Phase 3B（Delivery 之后跑）：tar tzf + unzip -l。

        业务规则、逻辑一致性的深度校验（第二阶段）。
        若 artifacts 中未产出 tar/zip，则返回 pass=True 的空结果（视为跳过，不阻断）。
        """
        result = ValidationResult(pass_=True)
        tar_gz_path = self._find_artifact(artifacts, ("tar_gz", ".tar.gz"))
        if tar_gz_path:
            run = self._run_with_retries(["tar", "tzf", tar_gz_path], cwd="/tmp")
            result.command_results.append(run)
            if run.returncode != 0:
                result.pass_ = False
        zip_path = self._find_artifact(artifacts, ("zip", ".zip"))
        if zip_path:
            run = self._run_with_retries(["unzip", "-l", zip_path], cwd="/tmp")
            result.command_results.append(run)
            if run.returncode != 0:
                result.pass_ = False
        return result

    @staticmethod
    def aggregate(
        source: ValidationResult,
        archives: ValidationResult,
        level: Union[ValidationBlockingLevel, str] = ValidationBlockingLevel.HARD_BLOCK,
    ) -> AggregatedValidationResult:
        """将两阶段结果合并为 AggregatedValidationResult，按 blocking_level 算 should_block_release。

        - OFF: 永不阻断
        - WARN: 永不阻断（warning 级，只在日志提示）
        - HARD_BLOCK（默认）: 任一阶段失败 → 强阻断
        """
        if isinstance(level, str):
            try:
                level_enum = ValidationBlockingLevel(level)
            except ValueError:
                warnings.warn(f"unknown blocking level={level!r}, fallback HARD_BLOCK")
                level_enum = ValidationBlockingLevel.HARD_BLOCK
        else:
            level_enum = level  # type: ignore[assignment]
        return AggregatedValidationResult(
            source=source,
            archives=archives,
            blocking_level=level_enum,  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------
    # 公开 API：兼容旧接口（Deprecation）
    # ------------------------------------------------------------
    def validate(
        self,
        project_root: str,
        artifacts: dict[str, str],
    ) -> ValidationResult:
        """执行完整验证流程（deprecated: 请改用 validate_source + validate_archives + aggregate）。

        Args:
            project_root: 项目根目录（执行 cargo 命令时作为 cwd）。
            artifacts:    delivery 产物字典，key 为 "tar_gz" / "zip" 或文件相对路径，
                          value 为对应文件的绝对路径。校验归档命令会从该字典中查找。

        Returns:
            ValidationResult：整体 pass 标志 + 每条命令的详细执行结果列表。
        """
        warnings.warn(
            "Validator.validate() is deprecated; use validate_source + validate_archives + Validator.aggregate()",
            DeprecationWarning,
            stacklevel=2,
        )
        src = self.validate_source(project_root)
        arc = self.validate_archives(artifacts)
        # 兼容旧接口：仍返回单 ValidationResult（把 archive 结果追加到 src 里）
        result = ValidationResult(pass_=src.pass_ and arc.pass_)
        result.command_results.extend(src.command_results)
        result.command_results.extend(arc.command_results)
        return result

    # ------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------
    @staticmethod
    def _find_artifact(
        artifacts: dict[str, str],
        key_suffixes: tuple[str, ...],
    ) -> Optional[str]:
        """从 artifacts 字典中查找 tar.gz / zip 路径（支持多种 key 命名风格）。"""
        if not artifacts:
            return None
        # 优先精确 key
        for k in key_suffixes:
            if k in artifacts and artifacts[k]:
                return artifacts[k]
        # 退化：按 value 后缀匹配
        for v in artifacts.values():
            if not v:
                continue
            vl = v.lower()
            for suffix in key_suffixes:
                if suffix.startswith(".") and vl.endswith(suffix):
                    return v
        return None

    def _run_with_retries(self, cmd: list[str], cwd: str) -> CommandRun:
        """对单条命令执行最多 retries 次重试，返回最后一次（或首次成功）的结果。"""
        last_run: Optional[CommandRun] = None
        backoff = self.initial_backoff_s
        for attempt in range(1, self.retries + 1):
            run = self._run_once(cmd, cwd, attempt)
            last_run = run
            if run.returncode == 0:
                return run
            # 失败时按指数退避等待（最后一次不等待）
            if attempt < self.retries and backoff > 0:
                time.sleep(backoff)
                backoff *= 2
        # 所有尝试均失败，返回最后一次结果
        assert last_run is not None
        return last_run

    def _run_once(self, cmd: list[str], cwd: str, attempt: int) -> CommandRun:
        """单次执行 subprocess 并封装结果（单测可通过 _run_hook 覆盖）。"""
        if self._run_hook is not None:
            return self._run_hook(cmd, cwd, attempt)

        t0 = time.monotonic()
        try:
            completed = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.timeout_s,
                check=False,
            )
            rc = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as e:
            rc = 124
            stdout = (
                (e.stdout or b"").decode("utf-8", errors="replace")
                if isinstance(e.stdout, (bytes, bytearray))
                else (e.stdout or "")
            )
            stderr = f"TIMEOUT after {self.timeout_s}s: {e}"
        except FileNotFoundError as e:
            rc = 127
            stdout = ""
            stderr = f"COMMAND NOT FOUND: {cmd[0]} ({e})"
        except Exception as e:  # noqa: BLE001 - 需要捕获所有执行期异常
            rc = 1
            stdout = ""
            stderr = f"EXEC ERROR: {type(e).__name__}: {e}"

        dur_ms = int((time.monotonic() - t0) * 1000)
        return CommandRun(
            cmd=list(cmd),
            cwd=cwd,
            attempt=attempt,
            returncode=rc,
            stdout=stdout,
            stderr=stderr,
            duration_ms=dur_ms,
        )


# ============================================================
# Module-level 别名（方便单测 / 外部调用）
# ============================================================
def aggregate_results(
    source: ValidationResult,
    archives: ValidationResult,
    *,
    level: Union[ValidationBlockingLevel, str, None] = None,
) -> AggregatedValidationResult:
    """Module-level 聚合入口。level 缺省 → HARD_BLOCK 默认。"""
    if level is None:
        level = ValidationBlockingLevel.HARD_BLOCK
    return Validator.aggregate(source, archives, level)
