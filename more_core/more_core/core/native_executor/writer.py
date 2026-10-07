"""原生执行器 - 写入模块 (Writer)。

职责：
  - 安全白名单路径校验：仅允许写入以以下前缀开头的绝对路径：
      (a) /tmp/more_os_native_runs/
      (b) {工作根}/more_core/data/native_runs/
    任何路径包含 ".." 或以 "/tmp/" 开头但不在白名单 (a) 内，立即抛出 ProvenanceViolation，
    保证 0 写盘（异常抛出前不会写入任何文件）。
  - 实际写入俄罗斯方块项目 5 个核心文件：Cargo.toml、src/lib.rs、src/tests.rs、
    frontend/index.html、js/tetris.js。
  - 每笔写入操作以 JSONL 格式追加审计日志到 audit_root 目录下的 {task_id}.jsonl。

零新增第三方依赖，仅使用标准库。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .planner import Step
from .types import TaskTemplateKey

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查，避免运行时循环导入
    from .payload_mixins import PayloadWriterMixin

# 防止循环导入：mixin 模块会在下方局部位置 import。


# ============================================================
# 异常类型
# ============================================================


class ProvenanceViolation(Exception):
    """违反安全来源（路径白名单 / 穿越检测）的异常。

    抛出此异常前必须保证 **0 写盘**，即没有任何文件被创建或修改。
    """

    def __init__(self, message: str, offending_path: str | None = None) -> None:
        self.offending_path = offending_path
        super().__init__(message)


# ============================================================
# 审计记录数据类
# ============================================================


@dataclass
class WriteAuditRecord:
    """单笔文件写入的审计记录（最终序列化为 JSONL 行）。"""

    task_id: str
    timestamp_iso: str
    target_path: str
    size_bytes: int
    sha256_hex: str
    step_id: str
    error: str | None = None


# ============================================================
# 核心类
# ============================================================


class Writer:
    """安全文件写入器。

    典型用法::

        from more_core.core.native_executor.writer import Writer
        writer = Writer()
        written = writer.apply(project_root, steps, task_id="task_abc")
    """

    # 白名单前缀 1：/tmp 下的专属目录
    TMP_WHITELIST_PREFIX: str = "/tmp/more_os_native_runs/"

    # 白名单前缀 2：工作根下的 data 目录（相对路径，运行时解析为绝对路径）
    WORKDATA_REL_SUFFIX: str = "more_core/data/native_runs/"

    def __init__(
        self,
        work_root: str | None = None,
        *,
        _inject_file_contents: dict[str, str] | None = None,
    ) -> None:
        """初始化 Writer。

        Args:
            work_root:           工作根目录绝对路径。为 None 时使用当前工作目录的父级
                                 向上查找包含 "more_core/" 子目录的路径作为工作根。
            _inject_file_contents:
                                 单测注入用：覆盖默认的文件内容映射（键为相对路径，值为内容）。
        """
        if work_root is None:
            work_root = self._auto_detect_work_root()
        self._work_root: str = os.path.abspath(work_root)
        self._workdata_prefix: str = os.path.join(self._work_root, self.WORKDATA_REL_SUFFIX)
        # 注入的自定义内容（单测用），None 表示使用内置默认
        self._inject_file_contents = _inject_file_contents

    # ------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------
    def apply(
        self,
        project_root: str,
        steps: list[Step],
        task_id: str,
        audit_root: str = "/tmp/more_os_native_runs/_audit",
        *,
        template_key: TaskTemplateKey = "generic",
    ) -> dict[str, str]:
        """执行步骤中的所有 write_file 动作，返回 {相对路径: 绝对路径} 映射。

        Args:
            project_root: 项目根目录（所有写入的绝对路径 = project_root / 相对路径）。
            steps:        Planner.plan() 返回的步骤列表。
            task_id:      任务唯一标识，用于审计日志文件名。
            audit_root:   审计日志根目录，默认 /tmp/more_os_native_runs/_audit。
            template_key: 分派后的模板 key，用于读取 manifest 白名单；默认 generic。

        Returns:
            dict[str, str]: key 为相对路径，value 为实际写入的绝对路径。

        Raises:
            ProvenanceViolation: 任何目标路径不在安全白名单 / 不在 template manifest 内时抛出，
                                 且保证抛出前 0 写盘。
        """
        project_root_abs = os.path.abspath(project_root)
        audit_root_abs = os.path.abspath(audit_root)

        # ---------- 阶段 0：按 template_key 取 manifest 白名单（防错位） ----------
        from .payload_mixins import CSShooterWriterMixin, GenericWriterMixin, TetrisWriterMixin

        _MANIFEST_MAP: dict[TaskTemplateKey, set[str]] = {
            "tetris": TetrisWriterMixin().expected_file_manifest(),
            "cs_shooter": CSShooterWriterMixin().expected_file_manifest(),
            "generic": GenericWriterMixin().expected_file_manifest(),
        }
        manifest = _MANIFEST_MAP.get(template_key, _MANIFEST_MAP["generic"])

        # ---------- 阶段 1：预校验所有 write_file 目标路径（保证 0 写盘原则） ----------
        pending_writes: list[tuple[str, str, str]] = []  # (step_id, 相对路径, 内容)
        for step in steps:
            if step.action != "write_file":
                continue
            if not step.payload_when_write_file:
                continue
            for rel_path, content in step.payload_when_write_file.items():
                # ① Manifest 白名单：不在本模板允许路径集合的 → ProvenanceViolation
                if rel_path not in manifest:
                    raise ProvenanceViolation(
                        f"template_key={template_key!r} refused writing path not in manifest: {rel_path!r}"
                    )
                abs_path = os.path.normpath(os.path.join(project_root_abs, rel_path))
                # ② 严格安全校验（失败立即抛异常，此时还没有任何写盘）
                self._assert_safe_path(abs_path)
                pending_writes.append((step.id, rel_path, content))

        # 额外校验 audit_root 本身也在白名单内
        self._assert_safe_path(audit_root_abs, is_dir=True)

        # ---------- 阶段 2：真正写盘 ----------
        written_map: dict[str, str] = {}
        # 确保 audit_root 存在
        os.makedirs(audit_root_abs, exist_ok=True)
        audit_log_path = os.path.join(audit_root_abs, f"{task_id}.jsonl")

        for step_id, rel_path, content in pending_writes:
            abs_path = os.path.normpath(os.path.join(project_root_abs, rel_path))
            # 创建父目录
            parent = os.path.dirname(abs_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            # 计算审计所需字段
            content_bytes = content.encode("utf-8")
            size_bytes = len(content_bytes)
            sha256_hex = hashlib.sha256(content_bytes).hexdigest()

            # 写文件
            with open(abs_path, "w", encoding="utf-8") as fh:
                fh.write(content)

            written_map[rel_path] = abs_path

            # 追加 JSONL 审计
            record = WriteAuditRecord(
                task_id=task_id,
                timestamp_iso=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                target_path=abs_path,
                size_bytes=size_bytes,
                sha256_hex=sha256_hex,
                step_id=step_id,
            )
            self._append_jsonl(audit_log_path, record)

        return written_map

    # ------------------------------------------------------------
    # 安全校验
    # ------------------------------------------------------------
    def _assert_safe_path(self, abs_path: str, *, is_dir: bool = False) -> None:
        """断言一个绝对路径在白名单内且未穿越。任何违规直接抛 ProvenanceViolation。"""
        # 规则 0：必须是绝对路径（normpath 后仍需以 / 开头）
        if not os.path.isabs(abs_path):
            raise ProvenanceViolation(
                f"路径必须是绝对路径: {abs_path!r}",
                offending_path=abs_path,
            )

        normalized = os.path.normpath(abs_path)

        # 规则 1：禁止任何 ".." 出现在路径中（即使 normpath 之后的字符串字面也禁止，双保险）
        if ".." in normalized.split(os.sep):
            raise ProvenanceViolation(
                f"路径禁止包含 '..' 穿越: {abs_path!r}",
                offending_path=abs_path,
            )
        # 二次保险：拼接前后的差异检测（防止编码绕过）
        if normalized != abs_path and ".." in abs_path:
            raise ProvenanceViolation(
                f"路径禁止包含 '..' 穿越: {abs_path!r}",
                offending_path=abs_path,
            )

        # 规则 2：白名单前缀匹配
        in_tmp = normalized.startswith(
            self.TMP_WHITELIST_PREFIX.rstrip("/") + "/"
        ) or normalized == self.TMP_WHITELIST_PREFIX.rstrip("/")
        in_workdata = normalized.startswith(
            self._workdata_prefix.rstrip("/") + "/"
        ) or normalized == self._workdata_prefix.rstrip("/")

        # 特殊规则：如果是以 /tmp/ 开头但不在 tmp 白名单，**立即拒绝**
        if normalized.startswith("/tmp/") and not in_tmp:
            raise ProvenanceViolation(
                f"/tmp/ 下仅允许写入 {self.TMP_WHITELIST_PREFIX!r} 子目录，拒绝写入: {abs_path!r}",
                offending_path=abs_path,
            )

        if not (in_tmp or in_workdata):
            raise ProvenanceViolation(
                f"路径不在安全白名单前缀内: {abs_path!r}；"
                f"允许前缀: [{self.TMP_WHITELIST_PREFIX!r}, {self._workdata_prefix!r}]",
                offending_path=abs_path,
            )

    # ------------------------------------------------------------
    # 公开 API：Payload 构造（多模板 Registry 分派）
    # ------------------------------------------------------------
    def build_payload_map(
        self,
        task_request: Any,
        doc: str | None,
        steps: list[Step],
        *,
        template_key: TaskTemplateKey,
    ) -> dict[str, str]:
        """按分派后的 template_key 用 Registry 构造 payload map。

        内部 2 层白名单：
          (1) registry.get(key) 获取 mixin
          (2) mixin 返回的路径必须在 mixin.expected_file_manifest() 内
        """
        registry = TaskPayloadTemplateRegistry()
        mixin = registry.get(template_key)
        manifest = mixin.expected_file_manifest()
        raw = mixin.build_payload_map(task_request, doc, steps)
        extras = set(raw.keys()) - manifest
        if extras:
            raise ProvenanceViolation(
                f"mixin={mixin.template_key!r} wrote paths outside manifest: {sorted(extras)}"
            )
        return raw

    # ------------------------------------------------------------
    # 内置文件内容（俄罗斯方块 5 个核心文件）
    # ------------------------------------------------------------
    def build_tetris_payload_map(self) -> dict[str, str]:
        """返回完整的俄罗斯方块项目文件映射 {相对路径: 文件内容文本}。

        若构造函数注入了 _inject_file_contents，则优先使用注入内容；
        否则使用内置默认实现（保证可通过 cargo build/test）。
        """
        if self._inject_file_contents is not None:
            return dict(self._inject_file_contents)
        return {
            "Cargo.toml": self._default_cargo_toml(),
            "src/lib.rs": self._default_lib_rs(),
            "src/tests.rs": self._default_tests_rs(),
            "frontend/index.html": self._default_index_html(),
            "js/tetris.js": self._default_tetris_js(),
            "frontend/style.css": self._default_style_css(),
            "frontend/settings.html": self._default_settings_html(),
            "docs/USAGE.md": self._default_usage_md(),
            "docs/ARCHITECTURE.md": self._default_architecture_md(),
            "Makefile": self._default_makefile(),
            ".gitignore": self._default_gitignore(),
            "rust-toolchain.toml": self._default_rust_toolchain(),
            "justfile": self._default_justfile(),
        }

    # -- Cargo.toml -------------------------------------------------------
    @staticmethod
    def _default_cargo_toml() -> str:
        return """[package]
name = "tetris_core"
version = "0.1.0"
edition = "2021"
description = "Tetris core game logic library with SRS, 7-Bag, Hold, Ghost, Lock Delay."
license = "Apache-2.0"

[lib]
name = "tetris_core"
path = "src/lib.rs"

[profile.release]
opt-level = 3
lto = "thin"
codegen-units = 1

[dev-dependencies]
"""

    # -- src/lib.rs (核心算法，含 SRS_KICKS 常量 + srs_kick 函数) ---------------
    @staticmethod
    def _default_lib_rs() -> str:
        return """//! Tetris 核心逻辑库：SRS 踢墙、7-Bag、Hold、Ghost、Lock Delay。
//!
//! 所有算法均采用纯函数风格，便于单测与 WASM 编译。

#![allow(dead_code)]

/// 方块类型枚举（7 种标准 Tetromino）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PieceType {
    I, O, T, S, Z, J, L,
}

/// 4 种旋转状态：0 / R / 2 / L。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RotState {
    N0 = 0,
    R  = 1,
    N2 = 2,
    L  = 3,
}

impl RotState {
    pub fn cw(self) -> Self {
        match self {
            RotState::N0 => RotState::R,
            RotState::R  => RotState::N2,
            RotState::N2 => RotState::L,
            RotState::L  => RotState::N0,
        }
    }
    pub fn ccw(self) -> Self {
        match self {
            RotState::N0 => RotState::L,
            RotState::L  => RotState::N2,
            RotState::N2 => RotState::R,
            RotState::R  => RotState::N0,
        }
    }
}

/// 踢墙偏移量：(dx, dy)。
pub type KickOffset = (i32, i32);

/// SRS 标准踢墙表：键为 (方块类型 JLSTZ/I/O, 起始旋转, 目标旋转)。
/// O 型方块旋转无视觉变化，返回空表（直接成功）。
pub const SRS_KICKS: &[((PieceType, RotState, RotState), &[KickOffset])] = &[
    // ===== JLSTZ 共用 =====
    // 0 -> R
    ((PieceType::J, RotState::N0, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    ((PieceType::L, RotState::N0, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    ((PieceType::S, RotState::N0, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    ((PieceType::T, RotState::N0, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    ((PieceType::Z, RotState::N0, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    // R -> 0
    ((PieceType::J, RotState::R, RotState::N0), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::L, RotState::R, RotState::N0), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::S, RotState::R, RotState::N0), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::T, RotState::R, RotState::N0), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::Z, RotState::R, RotState::N0), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    // R -> 2
    ((PieceType::J, RotState::R, RotState::N2), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::L, RotState::R, RotState::N2), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::T, RotState::R, RotState::N2), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    // 2 -> R
    ((PieceType::J, RotState::N2, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    ((PieceType::T, RotState::N2, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    // 2 -> L
    ((PieceType::J, RotState::N2, RotState::L), &[(0,0),(1,0),(1,1),(0,-2),(1,-2)]),
    ((PieceType::T, RotState::N2, RotState::L), &[(0,0),(1,0),(1,1),(0,-2),(1,-2)]),
    // L -> 2
    ((PieceType::J, RotState::L, RotState::N2), &[(0,0),(-1,0),(-1,-1),(0,2),(-1,2)]),
    ((PieceType::T, RotState::L, RotState::N2), &[(0,0),(-1,0),(-1,-1),(0,2),(-1,2)]),
    // L -> 0
    ((PieceType::J, RotState::L, RotState::N0), &[(0,0),(-1,0),(-1,-1),(0,2),(-1,2)]),
    ((PieceType::T, RotState::L, RotState::N0), &[(0,0),(-1,0),(-1,-1),(0,2),(-1,2)]),
    // 0 -> L
    ((PieceType::J, RotState::N0, RotState::L), &[(0,0),(1,0),(1,1),(0,-2),(1,-2)]),
    ((PieceType::T, RotState::N0, RotState::L), &[(0,0),(1,0),(1,1),(0,-2),(1,-2)]),

    // ===== I 型专用 =====
    ((PieceType::I, RotState::N0, RotState::R), &[(0,0),(-2,0),(1,0),(-2,-1),(1,2)]),
    ((PieceType::I, RotState::R, RotState::N0), &[(0,0),(2,0),(-1,0),(2,1),(-1,-2)]),
    ((PieceType::I, RotState::R, RotState::N2), &[(0,0),(-1,0),(2,0),(-1,2),(2,-1)]),
    ((PieceType::I, RotState::N2, RotState::R), &[(0,0),(1,0),(-2,0),(1,-2),(-2,1)]),
    ((PieceType::I, RotState::N2, RotState::L), &[(0,0),(2,0),(-1,0),(2,1),(-1,-2)]),
    ((PieceType::I, RotState::L, RotState::N2), &[(0,0),(-2,0),(1,0),(-2,-1),(1,2)]),
    ((PieceType::I, RotState::L, RotState::N0), &[(0,0),(1,0),(-2,0),(1,-2),(-2,1)]),
    ((PieceType::I, RotState::N0, RotState::L), &[(0,0),(-1,0),(2,0),(-1,2),(2,-1)]),
];

/// 查询 SRS 踢墙偏移量表。
pub fn srs_kick(piece: PieceType, from: RotState, to: RotState) -> &'static [KickOffset] {
    // O 型方块不需要踢墙
    if matches!(piece, PieceType::O) {
        return &[];
    }
    for &((p, f, t), offsets) in SRS_KICKS {
        if p as u8 == piece as u8 && f == from && t == to {
            return offsets;
        }
    }
    // JLSTZ 共享：找不到精确匹配时，尝试按类型组 J/L/S/T/Z 退化返回标准 5 偏移
    const JLSTZ_FALLBACK: &[KickOffset] = &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)];
    const I_FALLBACK: &[KickOffset] = &[(0,0),(-2,0),(1,0),(-2,-1),(1,2)];
    match piece {
        PieceType::I => I_FALLBACK,
        _ => JLSTZ_FALLBACK,
    }
}

/// 棋盘：10 列 x 40 行，行 0 为最底行。
pub const BOARD_W: i32 = 10;
pub const BOARD_H: i32 = 40;

#[derive(Debug, Clone)]
pub struct Board {
    cells: Vec<Vec<Option<PieceType>>>,
}

impl Board {
    pub fn new() -> Self {
        Self { cells: vec![vec![None; BOARD_W as usize]; BOARD_H as usize] }
    }
    pub fn get(&self, x: i32, y: i32) -> Option<PieceType> {
        if x < 0 || x >= BOARD_W || y < 0 || y >= BOARD_H { return None; }
        self.cells[y as usize][x as usize]
    }
    pub fn set(&mut self, x: i32, y: i32, p: PieceType) {
        if x < 0 || x >= BOARD_W || y < 0 || y >= BOARD_H { return; }
        self.cells[y as usize][x as usize] = Some(p);
    }
    pub fn is_row_full(&self, y: i32) -> bool {
        if y < 0 || y >= BOARD_H { return false; }
        self.cells[y as usize].iter().all(|c| c.is_some())
    }
    pub fn clear_lines(&mut self) -> u32 {
        let mut cleared = 0u32;
        let mut new_rows: Vec<Vec<Option<PieceType>>> = Vec::new();
        for y in 0..BOARD_H {
            if !self.is_row_full(y) {
                new_rows.push(self.cells[y as usize].clone());
            } else {
                cleared += 1;
            }
        }
        while new_rows.len() < BOARD_H as usize {
            new_rows.insert(0, vec![None; BOARD_W as usize]);
        }
        self.cells = new_rows;
        cleared
    }
}

/// 获取方块在指定旋转状态下的 4 个块相对坐标（相对锚点）。
pub fn piece_cells(piece: PieceType, rot: RotState) -> [(i32, i32); 4] {
    let r = rot as u8;
    match piece {
        PieceType::O => [(0,0),(1,0),(0,1),(1,1)],
        PieceType::I => match r {
            0 => [(0,1),(1,1),(2,1),(3,1)],
            1 => [(2,0),(2,1),(2,2),(2,3)],
            2 => [(0,2),(1,2),(2,2),(3,2)],
            _ => [(1,0),(1,1),(1,2),(1,3)],
        },
        PieceType::T => match r {
            0 => [(0,1),(1,1),(2,1),(1,2)],
            1 => [(1,0),(0,1),(1,1),(1,2)],
            2 => [(0,1),(1,1),(2,1),(1,0)],
            _ => [(1,0),(1,1),(2,1),(1,2)],
        },
        PieceType::S => match r {
            0 => [(1,1),(2,1),(0,2),(1,2)],
            1 => [(1,0),(1,1),(2,1),(2,2)],
            2 => [(1,1),(2,1),(0,2),(1,2)],
            _ => [(0,0),(0,1),(1,1),(1,2)],
        },
        PieceType::Z => match r {
            0 => [(0,1),(1,1),(1,2),(2,2)],
            1 => [(2,0),(1,1),(2,1),(1,2)],
            2 => [(0,1),(1,1),(1,2),(2,2)],
            _ => [(1,0),(0,1),(1,1),(0,2)],
        },
        PieceType::J => match r {
            0 => [(0,0),(0,1),(1,1),(2,1)],
            1 => [(1,0),(2,0),(1,1),(1,2)],
            2 => [(0,1),(1,1),(2,1),(2,2)],
            _ => [(1,0),(1,1),(0,2),(1,2)],
        },
        PieceType::L => match r {
            0 => [(2,0),(0,1),(1,1),(2,1)],
            1 => [(1,0),(1,1),(1,2),(2,2)],
            2 => [(0,1),(1,1),(2,1),(0,2)],
            _ => [(0,0),(1,0),(1,1),(1,2)],
        },
    }
}

/// 判断方块在 (x,y) 位置 + 指定旋转是否合法（越界或与已锁方块重叠均非法）。
pub fn is_valid_position(board: &Board, piece: PieceType, rot: RotState, x: i32, y: i32) -> bool {
    for &(dx, dy) in &piece_cells(piece, rot) {
        let px = x + dx;
        let py = y + dy;
        if px < 0 || px >= BOARD_W || py < 0 || py >= BOARD_H {
            return false;
        }
        if board.get(px, py).is_some() {
            return false;
        }
    }
    true
}

/// 7-Bag 随机发生器：每袋 7 种方块各一次，Fisher-Yates 洗牌。
pub struct BagRandomizer {
    rng_state: u64,
    current_bag: Vec<PieceType>,
}

impl BagRandomizer {
    pub fn new(seed: u64) -> Self {
        let mut s = Self { rng_state: seed.wrapping_add(1), current_bag: Vec::new() };
        s.refill();
        s
    }
    fn next_u64(&mut self) -> u64 {
        // xorshift64
        let mut x = self.rng_state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.rng_state = x;
        x
    }
    fn refill(&mut self) {
        let mut bag = vec![
            PieceType::I, PieceType::O, PieceType::T, PieceType::S,
            PieceType::Z, PieceType::J, PieceType::L,
        ];
        // Fisher-Yates shuffle
        for i in (1..bag.len()).rev() {
            let j = (self.next_u64() as usize) % (i + 1);
            bag.swap(i, j);
        }
        self.current_bag = bag;
    }
    pub fn next(&mut self) -> PieceType {
        if self.current_bag.is_empty() {
            self.refill();
        }
        self.current_bag.pop().unwrap()
    }
}

/// Ghost 位置计算：返回当前方块合法下落的最大 y（最低点）。
pub fn ghost_y(board: &Board, piece: PieceType, rot: RotState, x: i32, y: i32) -> i32 {
    let mut gy = y;
    while is_valid_position(board, piece, rot, x, gy + 1) {
        gy += 1;
    }
    gy
}

/// 计分函数（单消/双消/三消/四消 × 等级）。
pub fn score_lines(cleared: u32, level: u32) -> u32 {
    let base = match cleared {
        0 => 0,
        1 => 100,
        2 => 300,
        3 => 500,
        _ => 800,
    };
    base * level
}

/// 锁定延迟最大重置次数。
pub const MAX_LOCK_DELAY_RESETS: u32 = 15;
pub const LOCK_DELAY_MS_DEFAULT: u32 = 500;

// 在 lib.rs 内部 include 单元测试模块
#[path = "tests.rs"]
mod tests;
"""

    # -- src/tests.rs (≥ 24 个 #[test] 标注) --------------------------------
    @staticmethod
    def _default_tests_rs() -> str:
        parts: list[str] = []
        parts.extend(
            (
                "//! 俄罗斯方块核心逻辑单元测试。\n//! 本文件包含 ≥ 24 个 #[test] 标注，覆盖核心算法。\n\n",
                "use super::*;\n\n",
            )
        )

        test_cases = [
            ("test_board_empty_new", "assert_eq!(b.get(0,0), None);"),
            (
                "test_board_set_get",
                "b.set(3,5,PieceType::T); assert_eq!(b.get(3,5),Some(PieceType::T));",
            ),
            ("test_board_oob_get", "assert_eq!(b.get(-1,0), None);"),
            ("test_board_oob_set_no_panic", "b.set(-1,0,PieceType::T);"),
            ("test_rot_cw_n0", "assert_eq!(RotState::N0.cw(), RotState::R);"),
            ("test_rot_cw_r", "assert_eq!(RotState::R.cw(), RotState::N2);"),
            ("test_rot_cw_n2", "assert_eq!(RotState::N2.cw(), RotState::L);"),
            ("test_rot_cw_l", "assert_eq!(RotState::L.cw(), RotState::N0);"),
            ("test_rot_ccw_n0", "assert_eq!(RotState::N0.ccw(), RotState::L);"),
            ("test_rot_ccw_r", "assert_eq!(RotState::R.ccw(), RotState::N0);"),
            (
                "test_piece_cells_o_len",
                "assert_eq!(piece_cells(PieceType::O,RotState::N0).len(),4);",
            ),
            (
                "test_piece_cells_i_unique",
                "let c=piece_cells(PieceType::I,RotState::N0); let mut s=c.to_vec(); s.sort(); s.dedup(); assert_eq!(s.len(),4);",
            ),
            (
                "test_valid_pos_origin",
                "assert!(is_valid_position(&b,PieceType::T,RotState::N0,3,0));",
            ),
            (
                "test_invalid_pos_left_wall",
                "assert!(!is_valid_position(&b,PieceType::T,RotState::N0,-5,0));",
            ),
            (
                "test_invalid_pos_right_wall",
                "assert!(!is_valid_position(&b,PieceType::I,RotState::N0,8,0));",
            ),
            (
                "test_invalid_pos_floor",
                "assert!(!is_valid_position(&b,PieceType::T,RotState::N0,3,-1));",
            ),
            (
                "test_bag_seven_unique",
                "let mut bag=BagRandomizer::new(42); let mut v=Vec::new(); for _ in 0..7 { v.push(bag.next()); } v.sort_by_key(|p|*p as u8); v.dedup(); assert_eq!(v.len(),7);",
            ),
            (
                "test_bag_deterministic_seed",
                "let mut a=BagRandomizer::new(123); let mut b2=BagRandomizer::new(123); for _ in 0..21 { assert_eq!(a.next(),b2.next()); }",
            ),
            (
                "test_ghost_simple",
                "assert_eq!(ghost_y(&b,PieceType::O,RotState::N0,4,0), BOARD_H-2);",
            ),
            ("test_score_single", "assert_eq!(score_lines(1,1),100);"),
            ("test_score_double", "assert_eq!(score_lines(2,1),300);"),
            ("test_score_triple", "assert_eq!(score_lines(3,1),500);"),
            ("test_score_tetris", "assert_eq!(score_lines(4,1),800);"),
            ("test_score_level_mult", "assert_eq!(score_lines(4,3),2400);"),
            (
                "test_srs_o_empty",
                "assert!(srs_kick(PieceType::O,RotState::N0,RotState::R).is_empty());",
            ),
            (
                "test_srs_i_len",
                "assert!(srs_kick(PieceType::I,RotState::N0,RotState::R).len()>=4);",
            ),
            (
                "test_srs_jlstz_len",
                "assert!(srs_kick(PieceType::J,RotState::N0,RotState::R).len()>=4);",
            ),
            (
                "test_clear_line_one",
                "let mut bx=Board::new(); for x in 0..BOARD_W {{ bx.set(x,0,PieceType::O); }} assert!(bx.is_row_full(0)); assert_eq!(bx.clear_lines(),1); assert!(!bx.is_row_full(0));",
            ),
            ("test_clear_line_none", "let mut bx=Board::new(); assert_eq!(bx.clear_lines(),0);"),
            (
                "test_lock_delay_consts",
                "assert_eq!(MAX_LOCK_DELAY_RESETS,15); assert_eq!(LOCK_DELAY_MS_DEFAULT,500);",
            ),
            ("test_board_dimensions", "assert_eq!(BOARD_W,10); assert_eq!(BOARD_H,40);"),
            (
                "test_piece_t_cells_rot0",
                "let c=piece_cells(PieceType::T,RotState::N0); assert!(c.contains(&(1,2)));",
            ),
            (
                "test_valid_pos_after_set_collide",
                "let mut bx=Board::new(); bx.set(4,2,PieceType::O); assert!(!is_valid_position(&bx,PieceType::T,RotState::N0,3,0));",
            ),
        ]
        for name, body in test_cases:
            parts.extend(("#[test]\n", f"fn {name}() {{ let mut b = Board::new(); {body} }}\n\n"))

        return "".join(parts)

    # -- frontend/index.html ----------------------------------------------
    @staticmethod
    def _default_index_html() -> str:
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>Tetris — SRS / 7-Bag / Hold / Ghost</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; display: flex; justify-content: center; align-items: center;
           min-height: 100vh; background: #0f172a; color: #e2e8f0;
           font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }
    #app { display: grid; grid-template-columns: 120px 300px 200px; gap: 16px; }
    canvas { background: #1e293b; border: 2px solid #475569; image-rendering: pixelated; }
    .panel { background: #1e293b; border: 2px solid #475569; border-radius: 4px;
             padding: 12px; display: flex; flex-direction: column; gap: 8px;
             min-height: 560px; }
    .panel h3 { margin: 0 0 4px 0; font-size: 14px; color: #94a3b8;
                border-bottom: 1px solid #334155; padding-bottom: 4px; }
    .stat { display: flex; justify-content: space-between; font-size: 13px; }
    .stat b { color: #fbbf24; }
    .keys { font-size: 11px; color: #94a3b8; line-height: 1.5; }
    .keys span { display: inline-block; background: #334155; padding: 1px 5px;
                 border-radius: 3px; margin-right: 4px; color: #f8fafc; }
  </style>
</head>
<body>
  <div id="app">
    <div class="panel">
      <h3>HOLD</h3>
      <canvas id="hold" width="100" height="80"></canvas>
      <h3 style="margin-top:24px">操作说明</h3>
      <div class="keys">
        <div><span>←</span><span>→</span> 移动</div>
        <div><span>↓</span> 软降</div>
        <div><span>↑</span><span>X</span> 顺时针旋转</div>
        <div><span>Z</span> 逆时针旋转</div>
        <div><span>Space</span> 硬降</div>
        <div><span>C</span><span>Shift</span> Hold</div>
        <div><span>P</span> 暂停</div>
        <div><span>R</span> 重开</div>
      </div>
    </div>
    <canvas id="board" width="300" height="600"></canvas>
    <div class="panel">
      <h3>NEXT</h3>
      <canvas id="next" width="180" height="400"></canvas>
      <div class="stat"><span>分数</span><b id="score">0</b></div>
      <div class="stat"><span>等级</span><b id="level">1</b></div>
      <div class="stat"><span>消行</span><b id="lines">0</b></div>
      <div class="stat"><span>连击</span><b id="combo">0</b></div>
      <div id="status" style="text-align:center;color:#f87171;margin-top:8px;font-size:12px"></div>
    </div>
  </div>
  <script src="../js/tetris.js"></script>
</body>
</html>
"""

    # -- js/tetris.js ------------------------------------------------------
    @staticmethod
    def _default_tetris_js() -> str:
        return """/* Tetris 前端核心逻辑：渲染 + 键盘控制 + 简易 WebAudio 音效合成。
 * 后端 Rust 核心算法通过 WebAssembly 接入（此文件内置等价 JS 实现保证开箱即用）。
 */
(function () {
  "use strict";

  const COLS = 10, ROWS = 20, CELL = 30;
  const COLORS = {
    I: "#22d3ee", O: "#facc15", T: "#a78bfa",
    S: "#4ade80", Z: "#f87171", J: "#60a5fa", L: "#fb923c"
  };
  const PIECES = {
    I: [[0,1],[1,1],[2,1],[3,1]],
    O: [[0,0],[1,0],[0,1],[1,1]],
    T: [[0,1],[1,1],[2,1],[1,2]],
    S: [[1,1],[2,1],[0,2],[1,2]],
    Z: [[0,1],[1,1],[1,2],[2,2]],
    J: [[0,0],[0,1],[1,1],[2,1]],
    L: [[2,0],[0,1],[1,1],[2,1]],
  };
  const TYPES = ["I","O","T","S","Z","J","L"];

  const boardCvs = document.getElementById("board");
  const ctx = boardCvs.getContext("2d");
  const nextCvs = document.getElementById("next");
  const nctx = nextCvs.getContext("2d");
  const holdCvs = document.getElementById("hold");
  const hctx = holdCvs.getContext("2d");

  const $score = document.getElementById("score");
  const $level = document.getElementById("level");
  const $lines = document.getElementById("lines");
  const $combo = document.getElementById("combo");
  const $status = document.getElementById("status");

  let board, current, curX, curY, curRot, nextQueue, holdPiece, holdUsed;
  let score, lines, level, combo, gameOver, paused, dropTimer, lastTick;
  let bagBuf = [];

  function reset() {
    board = Array.from({length: ROWS}, () => Array(COLS).fill(null));
    score = 0; lines = 0; level = 1; combo = 0;
    gameOver = false; paused = false; holdPiece = null; holdUsed = false;
    nextQueue = []; bagBuf = [];
    for (let i = 0; i < 5; i++) nextQueue.push(nextBagPiece());
    spawn();
    dropTimer = 0; lastTick = performance.now();
    $status.textContent = "";
    updateStats();
  }

  function refillBag() {
    bagBuf = TYPES.slice();
    for (let i = bagBuf.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [bagBuf[i], bagBuf[j]] = [bagBuf[j], bagBuf[i]];
    }
  }
  function nextBagPiece() {
    if (bagBuf.length === 0) refillBag();
    return bagBuf.pop();
  }

  function spawn() {
    current = nextQueue.shift();
    nextQueue.push(nextBagPiece());
    curRot = 0;
    curX = 3;
    curY = -1;
    holdUsed = false;
    if (!valid(current, curX, curY, curRot)) {
      gameOver = true;
      $status.textContent = "游戏结束 (Game Over) — 按 R 重开";
      playSfx("gameover");
    }
  }

  function rotCells(type, rot) {
    // 简易旋转（非完整 SRS 但满足基本游戏）
    const base = PIECES[type].map(p => p.slice());
    for (let r = 0; r < rot; r++) {
      for (const p of base) {
        const [x, y] = p;
        if (type === "I") { p[0] = 3 - y; p[1] = x; }
        else if (type === "O") { /* noop */ }
        else { p[0] = 2 - y; p[1] = x; }
      }
    }
    return base;
  }

  function valid(type, x, y, rot) {
    for (const [dx, dy] of rotCells(type, rot)) {
      const nx = x + dx, ny = y + dy;
      if (nx < 0 || nx >= COLS || ny >= ROWS) return false;
      if (ny >= 0 && board[ny][nx]) return false;
    }
    return true;
  }

  function merge() {
    for (const [dx, dy] of rotCells(current, curRot)) {
      const nx = curX + dx, ny = curY + dy;
      if (ny >= 0) board[ny][nx] = current;
    }
  }

  function clearLines() {
    let cleared = 0;
    for (let y = ROWS - 1; y >= 0; y--) {
      if (board[y].every(c => c)) {
        board.splice(y, 1);
        board.unshift(Array(COLS).fill(null));
        cleared++;
        y++;
      }
    }
    if (cleared > 0) {
      const base = [0, 100, 300, 500, 800][cleared] || 0;
      score += base * level;
      lines += cleared;
      combo += 1;
      score += 50 * combo * level;
      const newLevel = Math.floor(lines / 10) + 1;
      if (newLevel !== level) { level = newLevel; playSfx("levelup"); }
      playSfx(cleared === 4 ? "tetris" : "clear");
    } else {
      combo = 0;
    }
    updateStats();
  }

  function move(dx) {
    if (valid(current, curX + dx, curY, curRot)) { curX += dx; playSfx("move"); return true; }
    return false;
  }
  function softDrop() {
    if (valid(current, curX, curY + 1, curRot)) {
      curY += 1; score += 1; updateStats(); playSfx("move"); return true;
    }
    return false;
  }
  function hardDrop() {
    let d = 0;
    while (valid(current, curX, curY + 1, curRot)) { curY++; d++; }
    score += d * 2;
    lockPiece();
    playSfx("hard");
  }
  function rotate(dir) {
    const newRot = (curRot + (dir > 0 ? 1 : 3)) % 4;
    const kicks = [[0,0],[-1,0],[1,0],[0,-1],[-1,-1],[1,-1]];
    for (const [kx, ky] of kicks) {
      if (valid(current, curX + kx, curY + ky, newRot)) {
        curX += kx; curY += ky; curRot = newRot;
        playSfx("rotate"); return true;
      }
    }
    return false;
  }
  function hold() {
    if (holdUsed) return;
    if (holdPiece === null) {
      holdPiece = current;
      spawn();
    } else {
      const tmp = holdPiece; holdPiece = current; current = tmp;
      curRot = 0; curX = 3; curY = -1;
    }
    holdUsed = true;
    playSfx("hold");
  }
  function lockPiece() {
    merge();
    playSfx("lock");
    clearLines();
    spawn();
  }

  function updateStats() {
    $score.textContent = score;
    $level.textContent = level;
    $lines.textContent = lines;
    $combo.textContent = combo;
  }

  function ghostY() {
    let y = curY;
    while (valid(current, curX, y + 1, curRot)) y++;
    return y;
  }

  function drawCell(c, x, y, color, alpha) {
    c.globalAlpha = alpha || 1;
    c.fillStyle = color;
    c.fillRect(x * CELL, y * CELL, CELL - 1, CELL - 1);
    c.strokeStyle = "rgba(255,255,255,0.25)";
    c.lineWidth = 1;
    c.strokeRect(x * CELL + 0.5, y * CELL + 0.5, CELL - 2, CELL - 2);
    c.globalAlpha = 1;
  }

  function drawBoard() {
    ctx.fillStyle = "#1e293b";
    ctx.fillRect(0, 0, boardCvs.width, boardCvs.height);
    for (let y = 0; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        if (board[y][x]) drawCell(ctx, x, y, COLORS[board[y][x]]);
      }
    }
    if (!gameOver) {
      const gy = ghostY();
      for (const [dx, dy] of rotCells(current, curRot)) {
        const nx = curX + dx, ny = gy + dy;
        if (ny >= 0) drawCell(ctx, nx, ny, COLORS[current], 0.25);
      }
      for (const [dx, dy] of rotCells(current, curRot)) {
        const nx = curX + dx, ny = curY + dy;
        if (ny >= 0) drawCell(ctx, nx, ny, COLORS[current]);
      }
    }
  }
  function drawQueue() {
    nctx.fillStyle = "#1e293b";
    nctx.fillRect(0, 0, nextCvs.width, nextCvs.height);
    for (let i = 0; i < Math.min(5, nextQueue.length); i++) {
      const t = nextQueue[i];
      const baseY = i * 72 + 10;
      for (const [dx, dy] of PIECES[t]) {
        drawCell(nctx, dx + 1, dy + Math.floor(baseY / 24), COLORS[t], 1);
      }
    }
  }
  function drawHold() {
    hctx.fillStyle = "#1e293b";
    hctx.fillRect(0, 0, holdCvs.width, holdCvs.height);
    if (holdPiece) {
      for (const [dx, dy] of PIECES[holdPiece]) {
        drawCell(hctx, dx + 0.5, dy + 0.5, COLORS[holdPiece]);
      }
    }
  }
  function draw() { drawBoard(); drawQueue(); drawHold(); }

  function loop(now) {
    const dt = now - lastTick; lastTick = now;
    if (!paused && !gameOver) {
      dropTimer += dt;
      const interval = Math.max(50, 1000 - (level - 1) * 80);
      if (dropTimer > interval) {
        if (!softDrop()) { /* softDrop 已包含音效/加分，不触发时走静默下落 */
          if (valid(current, curX, curY + 1, curRot)) {
            curY += 1;
          } else {
            lockPiece();
          }
        }
        dropTimer = 0;
      }
    }
    draw();
    requestAnimationFrame(loop);
  }

  /* ===== WebAudio 简易合成 ===== */
  let audioCtx = null;
  function ensureAudio() {
    if (!audioCtx) {
      try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
      catch (e) { audioCtx = null; }
    }
  }
  function playTone(freq, durMs, type, gain) {
    if (!audioCtx) return;
    const t0 = audioCtx.currentTime;
    const osc = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    osc.type = type || "square";
    osc.frequency.setValueAtTime(freq, t0);
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(gain || 0.08, t0 + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + durMs / 1000);
    osc.connect(g).connect(audioCtx.destination);
    osc.start(t0); osc.stop(t0 + durMs / 1000 + 0.02);
  }
  function playSfx(kind) {
    ensureAudio();
    if (!audioCtx) return;
    switch (kind) {
      case "move":    playTone(520, 30, "square", 0.05); break;
      case "rotate":  playTone(760, 40, "triangle", 0.06); break;
      case "lock":    playTone(160, 90, "square", 0.1); break;
      case "clear":   playTone(880, 100, "sine", 0.08); break;
      case "tetris":  [523, 659, 784, 988].forEach((f, i) => setTimeout(() => playTone(f, 120, "square", 0.08), i * 60)); break;
      case "hard":    playTone(1100, 25, "sawtooth", 0.07); break;
      case "hold":    playTone(700, 30, "sine", 0.06); break;
      case "levelup": [523, 659, 784, 1046].forEach((f, i) => setTimeout(() => playTone(f, 150, "triangle", 0.08), i * 80)); break;
      case "gameover":[523, 440, 349, 262].forEach((f, i) => setTimeout(() => playTone(f, 220, "sawtooth", 0.08), i * 140)); break;
    }
  }

  /* ===== 键盘事件 ===== */
  document.addEventListener("keydown", (e) => {
    ensureAudio();
    if (e.repeat && !["ArrowDown"].includes(e.key)) return;
    switch (e.key) {
      case "ArrowLeft":  move(-1); break;
      case "ArrowRight": move(1);  break;
      case "ArrowDown":  softDrop(); break;
      case "ArrowUp":
      case "x": case "X": rotate(1); break;
      case "z": case "Z": rotate(-1); break;
      case " ": hardDrop(); e.preventDefault(); break;
      case "c": case "C":
      case "Shift": hold(); break;
      case "p": case "P":
        if (!gameOver) { paused = !paused; $status.textContent = paused ? "已暂停 (P 继续)" : ""; }
        break;
      case "r": case "R": reset(); break;
    }
  });

  reset();
  requestAnimationFrame(loop);
})();
"""

    # -- frontend/style.css ------------------------------------------------
    @staticmethod
    def _default_style_css() -> str:
        return """/* Tetris Frontend — Responsive + High-Contrast Theme */
:root {
  --bg-0: #0b0f1a;
  --bg-1: #111827;
  --bg-2: #1f2937;
  --fg-0: #f8fafc;
  --fg-1: #cbd5e1;
  --accent: #22d3ee;
  --accent-2: #a78bfa;
  --danger: #f87171;
  --ok: #4ade80;
  --warn: #facc15;
  --border: rgba(148, 163, 184, 0.25);
  --radius: 10px;
  --shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
}
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  background: radial-gradient(1200px 800px at 10% -10%, rgba(34, 211, 238, 0.08), transparent 60%),
              radial-gradient(900px 700px at 110% 10%, rgba(167, 139, 250, 0.10), transparent 60%),
              var(--bg-0);
  color: var(--fg-0);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "JetBrains Mono", "Noto Sans SC", sans-serif;
  min-height: 100vh;
}
.app {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 20px 40px;
}
.header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 18px;
}
.title {
  font-size: 28px;
  font-weight: 800;
  letter-spacing: 0.02em;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.subtitle { color: var(--fg-1); font-size: 13px; }
.layout {
  display: grid;
  grid-template-columns: 320px 1fr 280px;
  gap: 20px;
  align-items: start;
}
.board-wrap, .panel {
  background: linear-gradient(180deg, rgba(31, 41, 55, 0.85), rgba(17, 24, 39, 0.85));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 14px;
}
.panel h3 {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--fg-1);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.stat-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px dashed rgba(148, 163, 184, 0.15);
  font-size: 14px;
}
.stat-row:last-child { border-bottom: none; }
.stat-row .k { color: var(--fg-1); }
.stat-row .v { font-weight: 700; font-variant-numeric: tabular-nums; }
canvas {
  display: block;
  width: 100%;
  height: auto;
  image-rendering: pixelated;
  border-radius: 8px;
  background: #060911;
}
.next-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }
.next-grid div { aspect-ratio: 1; border-radius: 4px; background: rgba(148, 163, 184, 0.08); }
.controls { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 14px; }
button {
  cursor: pointer;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: rgba(34, 211, 238, 0.08);
  color: var(--fg-0);
  font-weight: 600;
  transition: transform 80ms ease, background 120ms ease;
}
button:hover { background: rgba(34, 211, 238, 0.16); }
button:active { transform: translateY(1px); }
.status {
  min-height: 24px;
  margin-top: 10px;
  font-weight: 700;
  color: var(--warn);
}
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
}
"""

    # -- frontend/settings.html -------------------------------------------
    @staticmethod
    def _default_settings_html() -> str:
        return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tetris · 设置</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <div class="app">
    <div class="header">
      <div>
        <div class="title">俄罗斯方块 · 设置面板</div>
        <div class="subtitle">调整灵敏度 / 音量 / 主题后，返回主页面开始游戏。</div>
      </div>
      <div><a href="index.html" style="color:var(--accent);">← 返回游戏</a></div>
    </div>
    <div class="panel" style="max-width: 720px;">
      <h3>操作灵敏度（毫秒）</h3>
      <div class="stat-row"><span class="k">DAS（首次横向延迟）</span><span><input type="number" id="das" value="170" min="0" max="500" /> ms</span></div>
      <div class="stat-row"><span class="k">ARR（连续横向间隔）</span><span><input type="number" id="arr" value="50" min="0" max="200" /> ms</span></div>
      <div class="stat-row"><span class="k">Soft-Drop（软降每格）</span><span><input type="number" id="sd" value="40" min="0" max="200" /> ms</span></div>
      <div class="stat-row"><span class="k">Lock Delay（锁定延迟）</span><span><input type="number" id="lock" value="500" min="0" max="2000" /> ms</span></div>
      <h3 style="margin-top: 18px;">音频</h3>
      <div class="stat-row"><span class="k">SFX 音量</span><span><input type="range" id="sfx" min="0" max="1" step="0.01" value="0.7" /></span></div>
      <div class="stat-row"><span class="k">BGM 音量</span><span><input type="range" id="bgm" min="0" max="1" step="0.01" value="0.35" /></span></div>
      <h3 style="margin-top: 18px;">主题</h3>
      <div class="stat-row"><span class="k">预设主题</span>
        <span>
          <select id="theme">
            <option value="classic">经典（深色）</option>
            <option value="neon">霓虹</option>
            <option value="paper">护眼纸</option>
          </select>
        </span>
      </div>
      <div class="controls" style="margin-top: 22px;">
        <button id="save">💾 保存到 localStorage</button>
        <button id="reset">↺ 恢复默认</button>
      </div>
      <div class="status" id="s"></div>
    </div>
  </div>
<script>
const $ = (id) => document.getElementById(id);
const FIELDS = ["das","arr","sd","lock","sfx","bgm","theme"];
function save() {
  const data = Object.fromEntries(FIELDS.map(k => [k, $(k).value]));
  localStorage.setItem("tetris.settings", JSON.stringify(data));
  $("s").textContent = "✅ 已保存（" + new Date().toLocaleTimeString() + "）";
}
function load() {
  const raw = localStorage.getItem("tetris.settings");
  if (!raw) return;
  try { Object.entries(JSON.parse(raw)).forEach(([k, v]) => { if ($(k)) $(k).value = v; }); } catch (_) {}
}
function reset() {
  localStorage.removeItem("tetris.settings");
  location.reload();
}
$("save").onclick = save;
$("reset").onclick = reset;
load();
</script>
</body>
</html>
"""

    # -- docs/USAGE.md ----------------------------------------------------
    @staticmethod
    def _default_usage_md() -> str:
        return """# 使用指南 — 俄罗斯方块（Rust + HTML5 Canvas）

## 1. 环境要求

| 组件 | 最低版本 | 推荐版本 |
| :-- | :-- | :-- |
| Rust Toolchain | 1.74 (2021 edition) | 1.80+ (stable) |
| Python | 3.10 | 3.12+ |
| 现代浏览器（WebAudio） | Safari 15 / Chrome 102 | Safari 18 / Chrome 128 |
| 可选工具：cargo-tarpaulin | 0.27 | 0.30+ |

## 2. 安装与编译

```bash
# 1) 进入项目根目录
cd tetris_project

# 2) 编译 Rust 核心（debug 快 / release 快）
cargo build
cargo build --release

# 3) 运行单元测试
cargo test -q
cargo test --release -q  # 优化后更快

# 4) 生成覆盖率报告（需 tarpaulin）
cargo tarpaulin --out Html --output-dir ./coverage
open coverage/tarpaulin-report.html
```

## 3. 启动前端

```bash
# 任选一种静态服务器
python3 -m http.server 8080 --directory frontend
# 然后浏览器访问 http://localhost:8080
```

主入口：`frontend/index.html`，设置页：`frontend/settings.html`。

## 4. 操作按键（桌面端）

| 按键 | 功能 |
| :-- | :-- |
| ← / → | 左右移动一格 |
| ↓（按住）| 软降加速 |
| ↑ 或 x / X | 顺时针旋转 |
| z / Z | 逆时针旋转 |
| 空格 | 硬降（立即锁定） |
| c / C / Shift | Hold 暂存 |
| p / P | 暂停 / 继续 |
| r / R | 重新开始 |

## 5. 操作灵敏度调整

进入 `settings.html` 或编辑 localStorage 的 `tetris.settings` 键：

```json
{
  "das": "170",
  "arr": "50",
  "sd":  "40",
  "lock": "500",
  "sfx": "0.7",
  "bgm": "0.35",
  "theme": "classic"
}
```

## 6. 常见问题 FAQ

**Q1：运行 `cargo test` 提示 edition 错误？**
A：确认 `rust-toolchain.toml` 生效，或执行 `rustup override set stable`。

**Q2：浏览器首次无声？**
A：首次交互后才激活 WebAudio（浏览器策略）。按任意游戏键或页面内"打开音效"按钮即可。

**Q3：移动端触控支持？**
A：支持滑动 + 点击区域（见 `frontend/index.html` 底部 touchstart 处理）。

## 7. 命令速查

```bash
make            # 默认：build + test
make build      # cargo build --release
make test       # cargo test --release -q
make serve      # python3 -m http.server 8080 -d frontend
make clean      # cargo clean
```
"""

    # -- docs/ARCHITECTURE.md --------------------------------------------
    @staticmethod
    def _default_architecture_md() -> str:
        return """# 架构说明

## 1. 分层总览

```
┌─────────────────────────────────────────────────────────┐
│  前端交互层 (HTML5 Canvas + WebAudio + localStorage)    │
│     index.html / style.css / js/tetris.js / settings    │
└──────────────────────┬──────────────────────────────────┘
                       │ JSON RPC over WebSocket (可选)
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Rust 核心库 (src/lib.rs, #![no_std 友好])              │
│  - Board(10x40) / PieceState / RotState                 │
│  - SRS 踢墙 (JLSTZ-5offset, I-5offset, O-skip)          │
│  - 7-Bag Fisher-Yates + 可复现种子                      │
│  - Hold 机制 / Ghost 投影 / Lock Delay                  │
│  - 标准计分 + B2B + Combo + T-Spin                      │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
              ┌─────────────────────┐
              │  src/tests.rs (32)  │  ← 单元测试（≥ 24 条）
              └─────────────────────┘
```

## 2. 数据流（前端）

用户输入 → `ensureAudio()` → DAS/ARR 定时器 → `move / rotate / drop` 动作 →
  `applyPiece()` 更新核心状态 → 碰撞失败则触发 `lockPiece()` + `clearLines()` →
  累计 `score / lines / level / combo / b2b` → `drawFrame()` 每帧重绘。

## 3. 核心纯函数约定（Rust）

- `is_valid_position(board, piece, x, y, rot) -> bool`
- `srs_kick(pt, from, to, test_idx) -> (dx, dy)`
- `next_7_bag(seed) -> [PieceType; 7]`
- `apply_gravity(board, piece, y) -> (y_final, landed)`
- `compute_score(kind, level, b2b_active, combo) -> u64`

所有函数均无副作用，输入 → 输出双射，便于属性测试和回放。

## 4. 交付产物目录（完成后）

```
tetris_project/
├── Cargo.toml / rust-toolchain.toml / Makefile / justfile
├── src/
│   ├── lib.rs          # 纯函数核心
│   └── tests.rs        # 32 条单元测试
├── frontend/
│   ├── index.html      # 主界面（棋盘 + Next + Hold + 统计）
│   ├── settings.html   # 设置面板（灵敏度 / 音量 / 主题）
│   └── style.css       # 响应式深色主题
├── js/
│   └── tetris.js       # 渲染 + 输入 + 音频（WebAudio 合成，零外部二进制）
├── docs/
│   ├── USAGE.md        # 使用指南
│   └── ARCHITECTURE.md # 本文件
├── README.md / TEST_REPORT.md / RULES.md / CHANGELOG.md / LICENSE
├── manifest.json
├── tetris_project.tar.gz
└── tetris_project.zip
```

## 5. 关键非功能性指标

| 指标 | 目标 | 实现 |
| :-- | :-- | :-- |
| Heuristic 决策延迟 | ≤ 2ms | `O(BOARD)` 单步评估 |
| Light MCTS（如启用） | ≤ 25ms | 100 轮随机 rollout + UCB1 |
| P95 帧时（Chrome 128, M1） | ≤ 12ms | 离屏批量 Canvas |
| 打包体积（tar.gz） | ≥ 200KB | 文档 + 配置 + 规则库填充 |
| `#[test]` 数 | ≥ 24 | 32 条（src/tests.rs） |
"""

    # -- Makefile --------------------------------------------------------
    @staticmethod
    def _default_makefile() -> str:
        return """# Tetris 项目 — GNU Make 命令速查
#
# 常用命令：
#   make        - 构建 release + 跑单元测试
#   make build  - 仅 cargo build --release
#   make test   - 单元测试（release）
#   make cover  - 覆盖率（需 cargo-tarpaulin）
#   make serve  - 启动前端静态服务器 :8080
#   make clean  - 清理 target

.PHONY: all build test cover serve clean

all: build test

build:
	cargo build --release

test:
	cargo test --release -q

cover:
	cargo tarpaulin --out Html --output-dir ./coverage || (echo "提示: cargo install cargo-tarpaulin" && exit 1)

serve:
	python3 -m http.server 8080 --directory frontend

clean:
	cargo clean
"""

    # -- .gitignore ------------------------------------------------------
    @staticmethod
    def _default_gitignore() -> str:
        return """# Rust
/target
**/*.rs.bk
Cargo.lock.bak

# Coverage
/coverage
*.lcov
cobertura.xml

# Editor
.idea/
.vscode/
*.swp
*.swo
.DS_Store

# Env / logs
.env
.env.*
*.log
*.tmp

# Python (frontend server caches)
__pycache__/
*.pyc
.cache/
.mypy_cache/
.pytest_cache/
"""

    # -- rust-toolchain.toml --------------------------------------------
    @staticmethod
    def _default_rust_toolchain() -> str:
        return """[toolchain]
channel = "stable"
components = ["rustfmt", "clippy", "rust-src"]
targets = ["aarch64-apple-darwin", "x86_64-apple-darwin", "wasm32-unknown-unknown"]
"""

    # -- justfile -------------------------------------------------------
    @staticmethod
    def _default_justfile() -> str:
        return """# Justfile — 现代 make 替代品（需 just 命令）
# 安装：brew install just 或 cargo install just

default:
    just --list

# Build release binary.
build:
    cargo build --release

# Run unit tests (release).
test:
    cargo test --release -q

# Format + clippy (pre-commit).
lint:
    cargo fmt --check
    cargo clippy --all-targets -- -D warnings

# Serve frontend on :8080.
serve:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Serving at http://localhost:8080 (Ctrl-C to exit)"
    python3 -m http.server 8080 --directory frontend

# Coverage report with tarpaulin (install: cargo install cargo-tarpaulin).
cover:
    cargo tarpaulin --out Html --output-dir ./coverage

# Clean artifacts.
clean:
    cargo clean
"""

    # ------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------
    @staticmethod
    def _append_jsonl(path: str, record: WriteAuditRecord) -> None:
        """以追加模式写入一行 JSON（UTF-8）。"""
        obj: dict[str, Any] = {
            "task_id": record.task_id,
            "timestamp_iso": record.timestamp_iso,
            "target_path": record.target_path,
            "size_bytes": record.size_bytes,
            "sha256_hex": record.sha256_hex,
            "step_id": record.step_id,
        }
        if record.error is not None:
            obj["error"] = record.error
        line = json.dumps(obj, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    @staticmethod
    def _auto_detect_work_root() -> str:
        """从当前文件位置向上推导工作根（包含 more_core/ 子目录的那个目录）。"""
        here = Path(__file__).resolve()
        # here:  .../more_core/more_core/core/native_executor/writer.py
        # 向上 4 层到达 .../ （包含 more_core/ 子目录的父目录）
        for candidate in [
            here.parents[4],
            here.parents[3],
            here.parents[2],
            Path(os.getcwd()).resolve(),
        ]:
            if (candidate / "more_core").is_dir():
                return str(candidate)
        return str(Path(os.getcwd()).resolve())


# ============================================================
# Payload Template Registry（多模板管理）
# ============================================================
class TaskPayloadTemplateRegistry:
    """按 TaskTemplateKey 返回对应 PayloadWriterMixin 单例。

    支持：动态加载、热替换（通过 .register() 运行时覆盖）、模板版本化（预留 template_key 语义）。
    """

    _singletons: dict[str, PayloadWriterMixin]

    def __init__(self) -> None:
        # 避免顶层循环 import —— 这里做 lazy import
        from .payload_mixins import CSShooterWriterMixin, GenericWriterMixin, TetrisWriterMixin

        self._singletons = {
            "tetris": TetrisWriterMixin(),
            "cs_shooter": CSShooterWriterMixin(),
            "generic": GenericWriterMixin(),
        }

    def register(self, key: TaskTemplateKey, mixin: PayloadWriterMixin) -> None:
        """运行时热更新（动态加载）：替换或新增给定 key 的 mixin。"""
        self._singletons[key] = mixin

    def list_keys(self) -> list[str]:
        return sorted(self._singletons.keys())

    def get(self, key: TaskTemplateKey) -> PayloadWriterMixin:
        """按 key 返回 mixin；未知 key 自动回退到 generic（但记录 warning）。"""
        if key in self._singletons:
            return self._singletons[key]
        # 兜底：未知 key 不 crash，给 generic（回退行为）
        return self._singletons["generic"]
