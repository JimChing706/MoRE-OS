#!/usr/bin/env python3
"""构建 QNMing-MoRE-Code-Shop 初版源码包（可重复执行）。

做三件事：
  1. 从主仓 ``more_core/more_core/`` **提取**已验证的内核源码到
     ``src/more_core/``（保留内部相对导入，不改写包名，避免破坏 210 个模块的引用）
  2. 写入构建信息（源提交、时间、文件统计）
  3. 产出可分发包 ``dist/QNMing-MoRE-Code-Shop-<version>.zip`` + SHA256

用法::

    python tools/build.py            # 提取 + 打包
    python tools/build.py --check    # 仅校验提取结果是否与主仓一致
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PKG_ROOT.parents[1]
CORE_SRC = REPO_ROOT / "more_core" / "more_core"
VENDOR_DEST = PKG_ROOT / "src" / "more_core"
DIST_DIR = PKG_ROOT / "dist"

#: 不进入分发包的内容（运行时产物 / 缓存）
_EXCLUDE_DIRS = {"__pycache__", "data"}
_EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".db", ".db-shm", ".db-wal", ".jsonl", ".bak")


def _version() -> str:
    ns: dict[str, str] = {}
    exec((PKG_ROOT / "src" / "qnming_code_shop" / "__init__.py").read_text(encoding="utf-8"), ns)
    return str(ns["__version__"])


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _iter_sources() -> list[Path]:
    out: list[Path] = []
    for path in sorted(CORE_SRC.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        if path.name.endswith(_EXCLUDE_SUFFIXES):
            continue
        if path.suffix not in {".py", ".json", ".toml", ".md", ".txt"}:
            continue
        out.append(path)
    return out


def extract(verbose: bool = True) -> dict[str, int]:
    """把内核源码提取到 src/more_core/。"""
    if VENDOR_DEST.exists():
        shutil.rmtree(VENDOR_DEST)
    files = _iter_sources()
    for src in files:
        rel = src.relative_to(CORE_SRC)
        dest = VENDOR_DEST / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    stats: dict[str, int] = {}
    for src in files:
        top = src.relative_to(CORE_SRC).parts[0] if len(src.relative_to(CORE_SRC).parts) > 1 else "(root)"
        stats[top] = stats.get(top, 0) + 1

    # 构建信息
    info = PKG_ROOT / "src" / "qnming_code_shop" / "_build_info.py"
    info.write_text(
        '"""由 tools/build.py 生成，勿手改。"""\n\n'
        f'SOURCE_COMMIT = "{_git("rev-parse", "--short", "HEAD")}"\n'
        f'BUILD_TIME = "{time.strftime("%Y-%m-%dT%H:%M:%S%z")}"\n'
        f'VENDORED_FILES = {len(files)}\n',
        encoding="utf-8",
    )
    if verbose:
        print(f"提取内核源码: {len(files)} 个文件 → src/more_core/")
        for top, n in sorted(stats.items(), key=lambda kv: -kv[1])[:12]:
            print(f"    {top:20s} {n:3d}")
    return stats


def check() -> bool:
    """校验提取结果与主仓一致（逐文件 sha256）。"""
    ok = True
    for src in _iter_sources():
        dest = VENDOR_DEST / src.relative_to(CORE_SRC)
        if not dest.exists():
            print(f"  ✗ 缺失: {dest.relative_to(PKG_ROOT)}")
            ok = False
            continue
        if hashlib.sha256(src.read_bytes()).hexdigest() != hashlib.sha256(dest.read_bytes()).hexdigest():
            print(f"  ✗ 内容不一致: {dest.relative_to(PKG_ROOT)}")
            ok = False
    print("提取一致性: " + ("OK" if ok else "FAILED"))
    return ok


def package() -> Path:
    """打包 src/ + tools/ + docs/ + 元数据 为 zip。"""
    version = _version()
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DIST_DIR / f"QNMing-MoRE-Code-Shop-{version}.zip"
    if zip_path.exists():
        zip_path.unlink()

    includes = ["src", "tools", "docs", "examples", "README.md", "pyproject.toml",
                "LICENSE", ".gitignore"]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in includes:
            path = PKG_ROOT / name
            if not path.exists():
                continue
            if path.is_file():
                zf.write(path, f"QNMing-MoRE-Code-Shop-{version}/{name}")
                continue
            for f in sorted(path.rglob("*")):
                if not f.is_file() or "__pycache__" in f.parts:
                    continue
                zf.write(f, f"QNMing-MoRE-Code-Shop-{version}/{f.relative_to(PKG_ROOT)}")

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (zip_path.with_suffix(".zip.sha256")).write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    size_kb = zip_path.stat().st_size / 1024
    print(f"\n分发包: {zip_path.relative_to(REPO_ROOT)}  ({size_kb:.0f} KB)")
    print(f"SHA256: {digest}")
    return zip_path


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 QNMing-MoRE-Code-Shop")
    ap.add_argument("--check", action="store_true", help="仅校验提取一致性")
    args = ap.parse_args()
    if args.check:
        return 0 if check() else 1
    extract()
    if not check():
        return 1
    package()
    print("\n下一步: python tools/verify.py   # 离线自检提取后的包")
    return 0


if __name__ == "__main__":
    sys.exit(main())
