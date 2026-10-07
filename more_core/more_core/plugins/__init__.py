"""Plugin subsystem."""

from .interface import PluginContext, PluginInterface, PluginMetadata
from .manager import PluginManager
from .sdk import PluginBase, generate_plugin_manifest, scaffold_plugin

__all__ = [
    "PluginBase",
    "PluginContext",
    "PluginInterface",
    "PluginManager",
    "PluginMetadata",
    "generate_plugin_manifest",
    "scaffold_plugin",
]
