"""插件管理器（plugins/manager.py）测试 —— 覆盖补齐。

动态构造插件目录，覆盖发现 / 加载 / 激活 / 依赖 / 去激活全流程。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from more_core.core.errors import PluginError
from more_core.plugins.manager import PluginManager

_PLUGIN_SRC = """\
from more_core.plugins.interface import PluginMetadata


class Plugin:
    metadata = PluginMetadata(name={name!r}, version="1.0.0")

    def __init__(self):
        self.activated = False

    async def activate(self, ctx):
        self.activated = True

    async def deactivate(self):
        self.activated = False

    def capabilities(self):
        return {{"cap": True}}
"""


class _FakeCore:
    settings = object()
    event_bus = object()

    def __init__(self) -> None:
        self.logger = logging.getLogger("test.plugin")


def _make_plugin(
    root: Path,
    name: str,
    *,
    deps: list[str] | None = None,
    entry_point: str = "main",
    write_entry: bool = True,
    export_class: bool = True,
) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "1.0.0",
                "description": f"desc-{name}",
                "author": "tester",
                "dependencies": deps or [],
                "entry_point": entry_point,
                "capabilities": ["cap"],
            }
        ),
        encoding="utf-8",
    )
    if write_entry:
        src = _PLUGIN_SRC.format(name=name) if export_class else "x = 1\n"
        (d / f"{entry_point}.py").write_text(src, encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def test_discover_missing_dir_returns_empty(tmp_path):
    assert PluginManager(tmp_path / "nope").discover() == []


def test_discover_reads_manifests(tmp_path):
    _make_plugin(tmp_path, "plug_a")
    _make_plugin(tmp_path, "plug_b")
    (tmp_path / "not_a_plugin").mkdir()  # 无 plugin.json → 忽略

    mgr = PluginManager(tmp_path)
    found = mgr.discover()
    assert {m.name for m in found} == {"plug_a", "plug_b"}
    md = next(m for m in found if m.name == "plug_a")
    assert md.version == "1.0.0"
    assert md.author == "tester"
    assert md.capabilities == ["cap"]


def test_discover_invalid_manifest_raises(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "plugin.json").write_text('{"version": "1.0.0"}', encoding="utf-8")  # 缺 name
    with pytest.raises(PluginError):
        PluginManager(tmp_path).discover()


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def test_load_unknown_plugin_raises(tmp_path):
    with pytest.raises(PluginError) as ei:
        PluginManager(tmp_path).load("ghost")
    assert "unknown plugin" in str(ei.value)


def test_load_missing_entry_file_raises(tmp_path):
    _make_plugin(tmp_path, "no_entry", write_entry=False)
    mgr = PluginManager(tmp_path)
    mgr.discover()
    with pytest.raises(PluginError) as ei:
        mgr.load("no_entry")
    assert "entry missing" in str(ei.value)


def test_load_without_plugin_class_raises(tmp_path):
    _make_plugin(tmp_path, "no_cls", export_class=False)
    mgr = PluginManager(tmp_path)
    mgr.discover()
    with pytest.raises(PluginError) as ei:
        mgr.load("no_cls")
    assert "does not export class Plugin" in str(ei.value)


def test_load_returns_cached_instance(tmp_path):
    _make_plugin(tmp_path, "cached_plug")
    mgr = PluginManager(tmp_path)
    mgr.discover()
    first = mgr.load("cached_plug")
    assert mgr.load("cached_plug") is first


# ---------------------------------------------------------------------------
# activate / deactivate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activate_and_deactivate(tmp_path):
    _make_plugin(tmp_path, "live_plug")
    mgr = PluginManager(tmp_path)
    mgr.discover()
    core = _FakeCore()

    await mgr.activate("live_plug", core)
    assert mgr.is_active("live_plug") is True
    assert [m.name for m in mgr.active()] == ["live_plug"]
    assert mgr.load("live_plug").activated is True

    await mgr.activate("live_plug", core)  # 幂等
    assert mgr.is_active("live_plug") is True

    await mgr.deactivate("live_plug")
    assert mgr.is_active("live_plug") is False


@pytest.mark.asyncio
async def test_activate_local_dependency_first(tmp_path):
    _make_plugin(tmp_path, "dep_plug")
    _make_plugin(tmp_path, "main_plug", deps=["dep_plug"])
    mgr = PluginManager(tmp_path)
    mgr.discover()

    await mgr.activate("main_plug", _FakeCore())
    assert mgr.is_active("dep_plug") and mgr.is_active("main_plug")


@pytest.mark.asyncio
async def test_activate_missing_local_dependency_raises(tmp_path):
    _make_plugin(tmp_path, "lonely", deps=["nope_dep"])
    mgr = PluginManager(tmp_path)
    mgr.discover()
    with pytest.raises(PluginError) as ei:
        await mgr.activate("lonely", _FakeCore())
    assert "depends on missing" in str(ei.value)


@pytest.mark.asyncio
async def test_activate_missing_pip_dependency_raises(tmp_path):
    _make_plugin(tmp_path, "pip_plug", deps=["definitely-not-installed-pkg>=1.0"])
    mgr = PluginManager(tmp_path)
    mgr.discover()
    with pytest.raises(PluginError) as ei:
        await mgr.activate("pip_plug", _FakeCore())
    assert "missing Python package" in str(ei.value)


@pytest.mark.asyncio
async def test_deactivate_blocked_by_reverse_dependency(tmp_path):
    _make_plugin(tmp_path, "base_plug")
    _make_plugin(tmp_path, "child_plug", deps=["base_plug"])
    mgr = PluginManager(tmp_path)
    mgr.discover()
    core = _FakeCore()
    await mgr.activate("child_plug", core)  # 会先激活 base_plug

    with pytest.raises(PluginError) as ei:
        await mgr.deactivate("base_plug")
    assert "required by" in str(ei.value)


def test_list_returns_all_discovered(tmp_path):
    _make_plugin(tmp_path, "l1")
    mgr = PluginManager(tmp_path)
    mgr.discover()
    assert [m.name for m in mgr.list()] == ["l1"]
    assert mgr.active() == []
