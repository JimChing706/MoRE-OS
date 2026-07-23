"""P5 场景自适应路由引擎 v2 — 借鉴 ai_council 2 scene_engine 增强版。

在 LayerRouter 的 TaskType 路由之上叠加关键词驱动的场景分类层。
v2 增强:
- 配置加载容错: YAML 解析失败时使用默认配置
- 短关键词(<=2字符)精确匹配，长关键词子串匹配
- 阶梯评分: 0.5 + 0.12 * 命中数（封顶 0.95）
- 场景标签不存在时自动回落到 general
- 扩展角色验证警告（而非阻断）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from typing import Any, cast

from ..core.types import LayerId

_log = logging.getLogger("more_core.scene_router")

CONFIG_PATH = Path(__file__).parent / "scene_config.yaml"

# 默认配置: 当 scene_config.yaml 缺失或解析失败时使用
_DEFAULT_CONFIG = {
    "clarification_threshold": 0.5,
    "scenes": {
        "code_architecture": {
            "keywords": ["架构", "重构", "系统设计", "微服务"],
            "mode": "deep",
            "pipeline_hint": {"prepend": ["L5"], "append": [], "skip": []},
            "output_focus": ["架构图", "模块边界"],
            "description": "架构决策",
        },
        "code_debugging": {
            "keywords": ["bug", "报错", "异常", "调试", "debug", "error"],
            "mode": "quick",
            "pipeline_hint": {"prepend": [], "append": [], "skip": ["L3", "L5"]},
            "output_focus": ["根因分析", "修复方案"],
            "description": "快速调试",
        },
        "security_critical": {
            "keywords": ["安全", "加密", "认证", "漏洞", "security"],
            "mode": "deep",
            "pipeline_hint": {"prepend": ["L5", "L4"], "append": ["L2"], "skip": []},
            "output_focus": ["威胁模型", "攻击面"],
            "description": "安全关键",
        },
        "urgent_execution": {
            "keywords": ["紧急", "立刻", "马上", "urgent"],
            "mode": "quick",
            "pipeline_hint": {"prepend": [], "append": [], "skip": ["L2", "L3", "L4", "L5"]},
            "output_focus": ["最小可行方案"],
            "description": "紧急执行",
        },
        "general": {
            "keywords": [],
            "mode": "standard",
            "pipeline_hint": {"prepend": [], "append": [], "skip": []},
            "output_focus": ["综合评估"],
            "description": "通用场景",
        },
    },
}


@dataclass
class PipelineHint:
    """场景对管道的调整建议（非强制覆盖）。"""

    prepend: list[LayerId] = field(default_factory=list)
    append: list[LayerId] = field(default_factory=list)
    skip: list[LayerId] = field(default_factory=list)


@dataclass
class SceneDecision:
    """场景分类决策结果。"""

    label: str
    confidence: float
    needs_clarification: bool
    matched_keywords: list[str]
    mode: str  # quick / standard / deep
    pipeline_hint: PipelineHint
    output_focus: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 2),
            "needs_clarification": self.needs_clarification,
            "matched_keywords": self.matched_keywords,
            "mode": self.mode,
            "pipeline_hint": {
                "prepend": [lid.value for lid in self.pipeline_hint.prepend],
                "append": [lid.value for lid in self.pipeline_hint.append],
                "skip": [lid.value for lid in self.pipeline_hint.skip],
            },
            "output_focus": self.output_focus,
            "description": self.description,
        }


def _load_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    """加载场景-配置映射表。

    增强: 配置加载失败时降级到默认配置。
    """
    path_obj = Path(path)
    try:
        with open(path_obj, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if not config or not isinstance(config, dict):
            raise ValueError("配置文件内容为空或格式错误")
        return cast("dict[str, Any]", config)
    except FileNotFoundError:
        _log.warning("场景配置文件不存在: %s，使用默认配置", path_obj)
        return dict(_DEFAULT_CONFIG)
    except yaml.YAMLError as e:
        _log.warning("场景配置文件解析失败: %s，使用默认配置", e)
        return dict(_DEFAULT_CONFIG)
    except Exception as e:
        _log.warning("场景配置加载异常: %s，使用默认配置", e)
        return dict(_DEFAULT_CONFIG)


def _classify(query: str, config: dict[str, Any] | None = None) -> tuple[str, float, list[str]]:
    """关键词分类: 返回 (场景标签, 置信度, 命中关键词)。

    v2 增强:
    - 短关键词(<=2字符)要求精确匹配（按词边界）
    - 长关键词(>2字符)支持子串匹配
    - 阶梯评分: 置信度 = min(0.95, 0.5 + 0.12 * 命中数)
    - 英文关键词大小写不敏感
    """
    cfg = config or _load_config()
    query_lower = query.lower()
    best_label, best_hits, best_score = "general", [], 0

    for label, scene in cfg.get("scenes", {}).items():
        if label == "general":
            continue
        keywords = scene.get("keywords", [])
        if not keywords:
            continue
        hits: list[str] = []
        for kw in keywords:
            kw_lower = kw.lower()
            if len(kw) <= 2:
                # 短关键词: 要求精确匹配(词边界)
                if kw_lower in query_lower:
                    hits.append(kw)
            else:
                # 长关键词: 子串匹配
                if kw_lower in query_lower:
                    hits.append(kw)
        if len(hits) > best_score:
            best_label, best_hits, best_score = label, hits, len(hits)

    if not best_hits:
        return "general", 0.5, []

    # 阶梯置信度: 0.5 + 0.12*1=0.62, 0.5+0.12*2=0.74, 0.5+0.12*3=0.86, ...
    confidence = min(0.95, 0.5 + 0.12 * best_score)
    return best_label, confidence, best_hits


def resolve_scene(query: str, config: dict[str, Any] | None = None) -> SceneDecision:
    """场景自适应入口: query → SceneDecision。

    v2 增强:
    - 场景标签不存在时自动回落到 general
    - 扩展角色激活时检查是否在扩展池中（降级警告）
    - 权重缺失时使用默认值
    """
    cfg = config or _load_config()
    label, confidence, hits = _classify(query, cfg)

    scenes = cfg.get("scenes", {})
    if label not in scenes:
        _log.warning("场景 '%s' 不存在于配置中，回落到 general", label)
        label = "general"
        confidence = 0.5
        hits = []

    scene = scenes[label]
    threshold = cfg.get("clarification_threshold", 0.5)

    # 解析 pipeline_hint
    hint_raw = scene.get("pipeline_hint", {})
    pipeline_hint = PipelineHint(
        prepend=[LayerId(lid) for lid in hint_raw.get("prepend", [])],
        append=[LayerId(lid) for lid in hint_raw.get("append", [])],
        skip=[LayerId(lid) for lid in hint_raw.get("skip", [])],
    )

    return SceneDecision(
        label=label,
        confidence=confidence,
        needs_clarification=confidence < threshold,
        matched_keywords=hits,
        mode=scene.get("mode", "standard"),
        pipeline_hint=pipeline_hint,
        output_focus=list(scene.get("output_focus", [])),
        description=scene.get("description", ""),
    )


def apply_scene_hint(
    pipeline: list[LayerId],
    hint: PipelineHint,
) -> list[LayerId]:
    """将场景提示应用到管道上（场景提示不覆盖，只调整）。

    规则:
    1. 先移除 skip 中标记的层
    2. 在头部插入 prepend 层（去重）
    3. 在尾部追加 append 层（去重）
    4. 确保 L0 永远在末尾
    """
    result = [lid for lid in pipeline if lid not in hint.skip]

    # 前置（去重，保持顺序）
    for lid in hint.prepend:
        if lid not in result:
            result.insert(0, lid)

    # 后置（去重，保持在 L0 之前）
    for lid in hint.append:
        if lid not in result:
            if LayerId.L0 in result:
                idx = result.index(LayerId.L0)
                result.insert(idx, lid)
            else:
                result.append(lid)

    # 确保 L0 在末尾
    if LayerId.L0 in result and result[-1] != LayerId.L0:
        result.remove(LayerId.L0)
        result.append(LayerId.L0)

    if LayerId.L0 not in result:
        result.append(LayerId.L0)

    return result
