"""Tests for the plugin SDK."""

import json

from more_core.plugins.sdk import PluginBase, generate_plugin_manifest, scaffold_plugin


def test_generate_manifest():
    m = generate_plugin_manifest("test-plugin", version="1.0.0", author="dev")
    assert m["name"] == "test-plugin"
    assert m["version"] == "1.0.0"
    assert m["min_core_version"] == "0.3.0"


def test_scaffold_plugin(tmp_path):
    root = scaffold_plugin(tmp_path, "my-plugin", description="A test plugin")
    assert (root / "plugin.json").exists()
    assert (root / "main.py").exists()
    assert (root / "README.md").exists()
    manifest = json.loads((root / "plugin.json").read_text())
    assert manifest["name"] == "my-plugin"
    code = (root / "main.py").read_text()
    assert "class Plugin" in code


def test_plugin_base_capabilities():
    class TestPlugin(PluginBase):
        NAME = "test"
        VERSION = "0.2.0"
        CAPABILITIES = ["code"]

    p = TestPlugin()
    caps = p.capabilities()
    assert caps["name"] == "test"
    assert "code" in caps["capabilities"]
