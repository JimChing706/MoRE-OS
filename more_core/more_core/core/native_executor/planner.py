"""原生执行器 - 规划模块 (Planner)。

职责：
  - 定义 Step 数据类（单个执行步骤的结构化描述）。
  - Planner.plan() 对外提供两条路径：
      1) LLM 路径：尝试调用 core.execute() 生成步骤列表；
      2) Fallback 路径：LLM 失败时使用内置 RULE_BASED_TETRIS_PLAN（7步俄罗斯方块固定计划）。

零新增第三方依赖，仅使用标准库 dataclasses 与 typing。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Step:
    """单个执行步骤的结构化描述。

    Attributes:
        id:                  步骤唯一标识（字符串，例如 "s1_cargo_toml"）。
        title:               步骤人类可读标题（中文，便于审计日志与报告展示）。
        action:              动作类型，目前仅支持 "write_file" 或 "cmd"。
        depends_on:          前置依赖步骤 id 列表，空列表代表无依赖。
        expected_outputs:    执行后期望产生的文件相对路径列表（相对 project_root）。
        payload_when_write_file:
                             当 action == "write_file" 时使用的字典；
                             键为相对路径（相对 project_root），值为要写入的文件内容文本。
                             当 action == "cmd" 时该字段为 None。
        cmd_when_cmd:        当 action == "cmd" 时使用的命令字符串数组（argv 形式）；
                             当 action == "write_file" 时该字段为 None。
    """

    id: str
    title: str
    action: str
    depends_on: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    payload_when_write_file: Optional[dict[str, str]] = None
    cmd_when_cmd: Optional[list[str]] = None


# ============================================================
# RULE_BASED_TETRIS_PLAN: 俄罗斯方块固定 7 步计划
# 当 LLM 路径失败时 fallback 使用，保证在离线 / 无 LLM 场景也能构建项目骨架。
# ============================================================

_RULE_BASED_STEPS_RAW: list[dict[str, Any]] = [
    {
        "id": "s1_cargo_toml",
        "title": "写入 Rust 项目配置 Cargo.toml（定义包名、版本、edition、依赖）",
        "action": "write_file",
        "depends_on": [],
        "expected_outputs": [
            "Cargo.toml",
            "Makefile",
            ".gitignore",
            "rust-toolchain.toml",
            "justfile",
        ],
    },
    {
        "id": "s2_lib_rs",
        "title": "写入 src/lib.rs 核心算法（SRS 踢墙、7-Bag、Hold、Ghost、Lock Delay）",
        "action": "write_file",
        "depends_on": ["s1_cargo_toml"],
        "expected_outputs": ["src/lib.rs"],
    },
    {
        "id": "s3_tests_rs",
        "title": "写入 src/tests.rs 单元测试（≥ 24 个 #[test] 标注）",
        "action": "write_file",
        "depends_on": ["s2_lib_rs"],
        "expected_outputs": ["src/tests.rs"],
    },
    {
        "id": "s4_frontend_html",
        "title": "写入 frontend/index.html 前端页面骨架",
        "action": "write_file",
        "depends_on": ["s1_cargo_toml"],
        "expected_outputs": [
            "frontend/index.html",
            "frontend/style.css",
            "frontend/settings.html",
        ],
    },
    {
        "id": "s5_frontend_js",
        "title": "写入 js/tetris.js 前端交互逻辑（渲染 + 键盘事件 + 音频）",
        "action": "write_file",
        "depends_on": ["s4_frontend_html"],
        "expected_outputs": [
            "js/tetris.js",
            "docs/USAGE.md",
            "docs/ARCHITECTURE.md",
        ],
    },
    {
        "id": "s6_cargo_build",
        "title": "执行 cargo build --release -q 编译 Rust 库",
        "action": "cmd",
        "depends_on": ["s2_lib_rs", "s3_tests_rs"],
        "expected_outputs": ["target/release/"],
    },
    {
        "id": "s7_cargo_test",
        "title": "执行 cargo test --release -q 运行单元测试",
        "action": "cmd",
        "depends_on": ["s6_cargo_build"],
        "expected_outputs": [],
    },
]

RULE_BASED_TETRIS_PLAN: list[Step] = [Step(**raw) for raw in _RULE_BASED_STEPS_RAW]


class Planner:
    """执行计划生成器。

    典型用法::

        from more_core.core.native_executor.planner import Planner
        planner = Planner()
        steps = planner.plan(task_request, project_root)
    """

    # 允许在单测中注入 fake_execute 替换真实 core.execute 行为
    _llm_execute_fn: Any = None

    def __init__(self, llm_execute_fn: Any = None) -> None:
        """初始化 Planner。

        Args:
            llm_execute_fn: 可选，用于替换默认 LLM 执行函数（主要用于单测）。
                            签名需兼容 ``fn(task_request, project_root, doc) -> list[Step]``。
        """
        if llm_execute_fn is not None:
            self._llm_execute_fn = llm_execute_fn

    # ------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------
    def plan(
        self,
        task_request: Any,
        project_root: str,
        doc: Optional[str] = None,
    ) -> list[Step]:
        """生成执行步骤列表。

        执行路径（优先级从高到低）：
          0) 规则引擎多模板分派（仅明确命中 cs_shooter/tetris 模板时生效）
          1) LLM 路径（_try_llm_plan）
          2) 最终 fallback：RULE_BASED_TETRIS_PLAN（极端兜底，非日常路径）

        Args:
            task_request:   任务请求对象（通常是 TaskRequest 或兼容 duck-type）。
            project_root:   项目根目录绝对路径（LLM 路径可能使用）。
            doc:            可选附加文档字符串（ITD markdown 全文，分派器解析 frontmatter）。

        Returns:
            list[Step]: 结构化步骤列表。
        """
        # ---- 路径 0：规则引擎多模板分派（仅 cs_shooter/tetris 明确命中时生效）----
        # generic 兜底不在此抢占：无特征任务应继续走 LLM 路径（注入时）或
        # RULE_BASED_TETRIS_PLAN fallback，保证 Planner（LLM 优先）与
        # TemplateDispatcher（显式模板分派）两套契约互不冲突。
        try:
            selector = TaskTemplateSelector()
            key = selector.key_for(task_request, doc)
            if key in ("cs_shooter", "tetris"):
                plan = selector.plan_for_key(key)
                if plan:
                    return plan
        except Exception:
            pass

        # ---- 路径 1：LLM ----
        llm_result: Optional[list[Step]] = self._try_llm_plan(task_request, project_root, doc)
        if self._is_valid_step_list(llm_result):
            return llm_result  # type: ignore[return-value]

        # ---- 路径 2：最终 fallback 俄罗斯方块 ----
        return copy.deepcopy(RULE_BASED_TETRIS_PLAN)

    # ------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------
    def _try_llm_plan(
        self,
        task_request: Any,
        project_root: str,
        doc: Optional[str],
    ) -> Optional[list[Step]]:
        """尝试通过 LLM 路径生成步骤。失败统一返回 None 交给调用方 fallback。"""
        try:
            execute_fn = self._llm_execute_fn or self._default_core_execute
            result = execute_fn(task_request, project_root, doc)
            if result is None:
                return None
            return result
        except Exception:
            # 任何异常（未配置 LLM、网络错误、返回格式错误等）都 fallback
            return None

    @staticmethod
    def _default_core_execute(
        task_request: Any,
        project_root: str,
        doc: Optional[str],
    ) -> list[Step]:
        """默认 LLM 执行占位：直接抛异常触发 fallback。

        真实环境中应通过 ``Planner(llm_execute_fn=...)`` 或在子类中覆盖此方法，
        调用 ``more_core.MoRECore.execute(...)`` 获取 LLM 生成的步骤。
        这里保持零外部依赖，不直接 import MoRECore，避免循环引用。
        """
        raise NotImplementedError(
            "Planner._default_core_execute 未注入真实 LLM 执行函数，"
            "将自动 fallback 到 RULE_BASED_TETRIS_PLAN。"
        )

    @staticmethod
    def _is_valid_step_list(value: Any) -> bool:
        """校验 value 是否为「非空且所有元素均为 Step 实例」的列表。"""
        if not isinstance(value, list):
            return False
        if len(value) == 0:
            return False
        return all(isinstance(item, Step) for item in value)


# ====================================================================
# 多模板：CS 射击 / Generic 两套规则步骤；Tetris 已在顶部定义。
# ====================================================================

_CS_STEPS_RAW: list[dict[str, Any]] = [
    {
        "id": "cs_s1_ws_cargo",
        "title": "Cargo workspace 3 个子 crate 骨架",
        "action": "write_file",
        "depends_on": [],
        "expected_outputs": [
            "Cargo.toml", "Makefile", "rust-toolchain.toml", "justfile", ".gitignore",
            "shooter_core/Cargo.toml", "shooter_server/Cargo.toml", "shooter_bot/Cargo.toml",
        ],
    },
    {
        "id": "cs_s2_core",
        "title": "shooter_core: 武器/经济/回合/C4/帧同步 hash 纯规则",
        "action": "write_file",
        "depends_on": ["cs_s1_ws_cargo"],
        "expected_outputs": ["shooter_core/src/lib.rs", "shooter_core/src/tests.rs"],
    },
    {
        "id": "cs_s3_server",
        "title": "shooter_server: axum + WebSocket 帧同步房间管理 REST rooms",
        "action": "write_file",
        "depends_on": ["cs_s2_core"],
        "expected_outputs": [
            "shooter_server/src/lib.rs", "shooter_server/src/main.rs", "shooter_server/build.rs",
        ],
    },
    {
        "id": "cs_s4_bot",
        "title": "shooter_bot: 启发式 A* 寻路 + 目标优先级 + 武器切换",
        "action": "write_file",
        "depends_on": ["cs_s2_core"],
        "expected_outputs": ["shooter_bot/src/lib.rs", "shooter_bot/src/tests.rs"],
    },
    {
        "id": "cs_s5_frontend",
        "title": "前端: React + TS + Vite + IGameClientAdapter 两种实现",
        "action": "write_file",
        "depends_on": ["cs_s1_ws_cargo"],
        "expected_outputs": [
            "frontend/package.json", "frontend/vite.config.ts", "frontend/index.html",
            "frontend/src/App.tsx",
            "frontend/src/adapters/IGameClientAdapter.ts",
            "frontend/src/adapters/LocalInProcAdapter.ts",
            "frontend/src/adapters/WsAdapter.ts",
            "frontend/src/game/state.ts",
            "frontend/src/ui/HUD.tsx",
        ],
    },
    {
        "id": "cs_s6_docs_deploy",
        "title": "文档+部署: README 5 步 / USAGE / ARCH / Dockerfile / compose",
        "action": "write_file",
        "depends_on": ["cs_s3_server", "cs_s4_bot", "cs_s5_frontend"],
        "expected_outputs": [
            "README.md", "docs/USAGE.md", "docs/ARCHITECTURE.md",
            "deploy/Dockerfile", "deploy/docker-compose.yml",
        ],
    },
    {
        "id": "cs_s7_cargo_test",
        "title": "cargo test --workspace --release -q",
        "action": "cmd",
        "depends_on": ["cs_s2_core", "cs_s3_server", "cs_s4_bot"],
        "expected_outputs": [],
        "cmd_when_cmd": ["cargo", "test", "--workspace", "--release", "-q"],
    },
]
RULE_BASED_CS_SHOOTER_PLAN: list[Step] = [Step(**r) for r in _CS_STEPS_RAW]

_GENERIC_STEPS_RAW: list[dict[str, Any]] = [
    {
        "id": "g_s1_scaffold",
        "title": "通用代码空壳：README/Cargo.toml/Dockerfile/USAGE/ARCH/Makefile/.gitignore",
        "action": "write_file",
        "depends_on": [],
        "expected_outputs": [
            "README.md", "Cargo.toml", "Dockerfile",
            "docs/USAGE.md", "docs/ARCHITECTURE.md",
            "Makefile", ".gitignore",
        ],
    },
]
RULE_BASED_GENERIC_SCAFFOLD_PLAN: list[Step] = [Step(**r) for r in _GENERIC_STEPS_RAW]


class TaskTemplateSelector:
    """按任务类型/标题/标签分派到 template_key（优先级 CS>Tetris>Generic）。"""

    # 路由修复（RESIDUAL_RISKS R-04）：
    # 旧写法 `(?i)(cs|shooter|...|fps|...)` 是裸子串匹配，导致
    # docs / metrics / statistics / specs（都含 "cs"）被误判为 CS 射击任务。
    # 现在分强弱两级：强信号单独命中；弱信号（cs / fps 这类歧义词）
    # 必须与"游戏/对战"语境共现，避免把"帧率 fps"当成射击游戏。
    CS_STRONG_RE = r"(?i)(?:\b(?:shooter|counter[\s_-]?strike)\b|射击|第一人称|枪战)"
    CS_WEAK_RE = r"(?i)(?:\b(?:cs|fps)\b)"
    CS_CONTEXT_RE = r"(?i)(?:游戏|对战|竞技|\bgame\b|\barena\b)"
    TETRIS_RE = r"(?i)(?:\b(?:tetris)\b|俄罗斯方块|方块消除|消行)"

    def _frontmatter_title_type_tags(self, doc: Optional[str]) -> tuple[str, str, list[str]]:
        title = typ = ""
        tags: list[str] = []
        if not doc:
            return title, typ, tags
        in_fm = False
        fm_lines: list[str] = []
        for line in doc.splitlines():
            s = line.strip()
            if s == "---":
                if not in_fm:
                    in_fm = True
                    continue
                break
            if in_fm:
                fm_lines.append(s)
        text = "\n".join(fm_lines)
        import re as _re
        m = _re.search(r"(?m)^title:\s*(.+)$", text)
        if m:
            title = m.group(1).strip().strip("\"'")
        m = _re.search(r"(?m)^type:\s*(.+)$", text)
        if m:
            typ = m.group(1).strip().strip("\"'")
        m = _re.search(r"(?m)^tags:\s*\[([^\]]*)\]", text)
        if m:
            tags = [t.strip().strip("\"'").lower() for t in m.group(1).split(",") if t.strip()]
        return title, typ, tags

    def key_for(self, task_request: Any, doc: Optional[str]) -> str:
        title, typ, tags = self._frontmatter_title_type_tags(doc)
        q = getattr(task_request, "query", "") or ""
        corpus = " ".join(filter(None, [title, typ, q, *tags]))
        import re as _re
        if _re.search(self.CS_STRONG_RE, corpus):
            return "cs_shooter"
        if _re.search(self.CS_WEAK_RE, corpus) and _re.search(self.CS_CONTEXT_RE, corpus):
            return "cs_shooter"
        if _re.search(self.TETRIS_RE, corpus):
            return "tetris"
        return "generic"

    def plan_for_key(self, key: str) -> list[Step]:
        import copy as _copy
        if key == "tetris":
            return _copy.deepcopy(RULE_BASED_TETRIS_PLAN)
        if key == "cs_shooter":
            return _copy.deepcopy(RULE_BASED_CS_SHOOTER_PLAN)
        return _copy.deepcopy(RULE_BASED_GENERIC_SCAFFOLD_PLAN)
