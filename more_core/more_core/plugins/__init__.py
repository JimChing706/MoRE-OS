"""Plugin subsystem."""

from .interface import PluginInterface, PluginMetadata, PluginContext
from .manager import PluginManager
from .sdk import PluginBase, scaffold_plugin, generate_plugin_manifest

__all__ = [
    "PluginInterface",
    "PluginMetadata",
    "PluginContext",
    "PluginManager",
    "PluginBase",
    "scaffold_plugin",
    "generate_plugin_manifest",
]
