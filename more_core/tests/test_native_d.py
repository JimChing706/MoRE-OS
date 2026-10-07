"""单测：Delivery (delivery.py)

目标：覆盖 README.md 10 条 [x] AC、TEST_REPORT.md 6 章、manifest.json (path/size_bytes/sha256 前 16 位)、
tar.gz + zip 双份打包、tar.gz / zip 内顶层目录名 == project_prefix。
共 ≥ 5 tests。
"""

import sys
import os
import json
import tarfile
import zipfile
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path


from more_core.core.native_executor.delivery import (
    Delivery,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _make_source_project(with_cargo: bool = True) -> Path:
    """在白名单临时目录中构造一个最小的俄罗斯方块源码项目（用于交付打包）。"""
    base = Path("/tmp/more_os_native_runs")
    base.mkdir(parents=True, exist_ok=True)
    proj = Path(tempfile.mkdtemp(prefix="dlv_", dir=str(base)))
    # 写入最小源文件集合
    (proj / "src").mkdir(parents=True, exist_ok=True)
    (proj / "frontend").mkdir(parents=True, exist_ok=True)
    (proj / "js").mkdir(parents=True, exist_ok=True)
    if with_cargo:
        (proj / "Cargo.toml").write_text(
            '[package]\nname = "tt"\nversion = "0.1.0"\nedition = "2021"\n',
            encoding="utf-8",
        )
    (proj / "src" / "lib.rs").write_text(
        "pub const X: i32 = 1;\npub fn srs_kick() {}\n",
        encoding="utf-8",
    )
    tests_body = "\n".join(
        f"#    [test]\n    fn t_{i}() {{ assert!(true); }}\n".replace("    ", "").replace(
            "#    [", "#["
        )
        for i in range(26)
    )
    (proj / "src" / "tests.rs").write_text(tests_body, encoding="utf-8")
    (proj / "frontend" / "index.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    (proj / "js" / "tetris.js").write_text("console.log('ok');", encoding="utf-8")
    return proj


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def test_delivery_readme_has_10_checked_ac_items():
    """README.md 必须包含恰好 ≥ 10 条 '- [x] ...' 的已实现 AC。"""
    proj = _make_source_project()
    d = Delivery(_use_system_tar=False, _use_system_zip=False)
    art = d.run(str(proj), project_prefix="tp-ac10")
    readme = Path(art.readme_path).read_text(encoding="utf-8")
    checked = [ln for ln in readme.splitlines() if ln.startswith("- [x] ")]
    assert len(checked) >= 10, f"README 只找到 {len(checked)} 条 [x] AC"


def test_delivery_test_report_has_6_chapters():
    """TEST_REPORT.md 必须包含 6 章的标题行（Delivery.TEST_REPORT_CHAPTERS 内容）。"""
    proj = _make_source_project()
    d = Delivery(_use_system_tar=False, _use_system_zip=False)
    art = d.run(str(proj), project_prefix="tp-ch6")
    text = Path(art.test_report_path).read_text(encoding="utf-8")
    for i, ch_title in enumerate(Delivery.TEST_REPORT_CHAPTERS):
        # 章节标题可能包含 "1. xxx" 或 "## 1. xxx" 格式，用子串匹配即可
        assert (
            ch_title[:16] in text
            or f"## {ch_title[:20]}" in text
            or ch_title.split(" (")[0] in text
        ), f"第 {i + 1} 章标题缺失或格式不符: {ch_title!r}"
    # 额外确认 6 章都存在（含"执行环境/测试范围/单元测试/构建验证/归档完整性/SHA256"关键词）
    keywords = ["执行环境", "测试范围", "单元测试", "构建验证", "归档完整性", "SHA256"]
    for kw in keywords:
        assert kw in text, f"TEST_REPORT.md 中缺少关键词: {kw}"


def test_delivery_manifest_has_path_size_sha_prefix16_for_each_entry():
    """manifest.json 每个条目都必须有 path / size_bytes / sha256_prefix16，且 sha 前缀恰好 16 hex。"""
    proj = _make_source_project()
    d = Delivery(_use_system_tar=False, _use_system_zip=False)
    art = d.run(str(proj), project_prefix="tp-mf")
    mf_path = Path(art.manifest_path)
    data = json.loads(mf_path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) >= 4
    for entry in data:
        assert "path" in entry and isinstance(entry["path"], str)
        assert "size_bytes" in entry and isinstance(entry["size_bytes"], int)
        assert entry["size_bytes"] >= 0
        assert "sha256_prefix16" in entry
        sha = entry["sha256_prefix16"]
        assert len(sha) == 16, f"sha256 前缀长度 != 16: {sha!r}"
        assert all(c in "0123456789abcdef" for c in sha), f"sha256 前缀非十六进制小写: {sha!r}"
    # manifest 中应当包含 Cargo.toml / src/lib.rs / src/tests.rs / frontend/index.html / js/tetris.js
    paths = {e["path"] for e in data}
    for required in ("src/lib.rs", "src/tests.rs", "frontend/index.html", "js/tetris.js"):
        assert required in paths, f"manifest 中缺少 {required}"


def test_delivery_creates_tar_gz_and_zip_and_top_level_dir_matches_prefix():
    """生成 .tar.gz + .zip 两份压缩包，且内部顶层目录 == project_prefix。"""
    proj = _make_source_project()
    output_dir = Path(tempfile.mkdtemp(prefix="out_", dir="/tmp/more_os_native_runs"))
    d = Delivery(_use_system_tar=False, _use_system_zip=False)
    prefix = "tetris_delivery_pack_v1"
    art = d.run(str(proj), project_prefix=prefix, output_dir=str(output_dir))

    # 两份压缩包都存在
    assert Path(art.tar_gz_path).is_file(), f"tar.gz 不存在: {art.tar_gz_path}"
    assert Path(art.zip_path).is_file(), f"zip 不存在: {art.zip_path}"
    assert art.tar_gz_path.endswith(".tar.gz")
    assert art.zip_path.endswith(".zip")

    # tar.gz 顶层目录前缀检查
    with tarfile.open(art.tar_gz_path, "r:gz") as tf:
        names = tf.getnames()
        assert len(names) >= 5, f"tar.gz 内容不足: {names}"
        top_levels = {n.split("/")[0] for n in names if n}
        assert top_levels == {prefix}, f"tar.gz 顶层目录必须恰好为 {prefix!r}，实际: {top_levels}"

    # zip 顶层目录前缀检查
    with zipfile.ZipFile(art.zip_path, "r") as zf:
        names = zf.namelist()
        assert len(names) >= 5
        top_levels = {n.split("/")[0] for n in names if n}
        assert top_levels == {prefix}, f"zip 顶层目录必须恰好为 {prefix!r}，实际: {top_levels}"
        # zip CRC 健康检查（无损坏条目）
        assert zf.testzip() is None, "zip 文件 CRC 校验失败"


def test_delivery_artifact_roundtrip_field_values():
    """DeliveryArtifact 返回字段与 project_prefix / output_dir 自洽。"""
    proj = _make_source_project()
    out_dir = Path(tempfile.mkdtemp(prefix="artchk_", dir="/tmp/more_os_native_runs"))
    d = Delivery(_use_system_tar=False, _use_system_zip=False)
    prefix = "rt_tetris_2026"
    art = d.run(str(proj), project_prefix=prefix, output_dir=str(out_dir))
    assert art.project_prefix == prefix
    # macOS 下 /tmp 是 /private/tmp 的软链，使用 Path.resolve() 比较而不是字符串
    assert Path(art.output_dir).resolve() == Path(out_dir).resolve()
    assert Path(art.tar_gz_path).parent.resolve() == Path(out_dir).resolve()
    assert Path(art.zip_path).parent.resolve() == Path(out_dir).resolve()
    # README / TEST_REPORT / manifest 都写在 project_root 下
    for p in (art.readme_path, art.test_report_path, art.manifest_path):
        assert Path(p).is_file(), f"交付文件缺失: {p}"
        assert Path(p).resolve().parent == Path(proj).resolve()


def test_delivery_manifest_sha_prefix16_matches_full_sha():
    """从 manifest 取一个条目，验证 sha256_prefix16 确实等于真实 SHA256 前 16 位。"""
    import hashlib

    proj = _make_source_project()
    d = Delivery(_use_system_tar=False, _use_system_zip=False)
    art = d.run(str(proj), project_prefix="sha-verify")
    data = json.loads(Path(art.manifest_path).read_text(encoding="utf-8"))
    # 找一个我们知道存在的文件
    by_path = {e["path"]: e for e in data}
    target_rel = "Cargo.toml" if "Cargo.toml" in by_path else "src/lib.rs"
    entry = by_path[target_rel]
    real_content = (proj / target_rel).read_bytes()
    real_sha = hashlib.sha256(real_content).hexdigest()
    assert entry["sha256_prefix16"] == real_sha[:16]
    assert entry["size_bytes"] == len(real_content)


def test_delivery_readme_contains_project_prefix_in_title():
    """README.md 的标题行（H1）中包含 project_prefix。"""
    proj = _make_source_project()
    d = Delivery(_use_system_tar=False, _use_system_zip=False)
    prefix = "MY-SPECIAL-PREFIX"
    art = d.run(str(proj), project_prefix=prefix)
    readme = Path(art.readme_path).read_text(encoding="utf-8")
    first_line = readme.splitlines()[0]
    assert prefix in first_line and first_line.startswith("# "), (
        f"README 首行应为 '# {prefix} ...'，实际: {first_line!r}"
    )
