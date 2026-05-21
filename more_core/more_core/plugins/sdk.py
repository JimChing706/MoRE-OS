"""Plugin SDK — helpers for plugin authors.

Provides base classes and utilities so that creating a ``more-plugin-*``
package is simple and consistent:

    from more_core.plugins.sdk import PluginBase

    class Plugin(PluginBase):
        NAME = "my-plugin"
        VERSION = "0.1.0"

        async def activate(self, ctx):
            ctx.core.tools.register(...)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .interface import PluginContext, PluginMetadata

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime.orchestrator import MoRECore


class PluginBase:
    """Convenience base class for plugin implementations.

    Subclass this instead of implementing the raw :class:`PluginInterface`
    protocol to get sensible defaults.
    """

    NAME: str = "unnamed"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = ""
    AUTHOR: str = ""
    CAPABILITIES: tuple[str, ...] = ()
    DEPENDENCIES: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.metadata = PluginMetadata(
            name=self.NAME,
            version=self.VERSION,
            description=self.DESCRIPTION,
            author=self.AUTHOR,
            capabilities=list(self.CAPABILITIES),
            dependencies=list(self.DEPENDENCIES),
        )
        self._ctx: PluginContext | None = None

    @property
    def core(self) -> "MoRECore":
        assert self._ctx is not None, "plugin not activated"
        return self._ctx.core

    async def activate(self, ctx: PluginContext) -> None:
        self._ctx = ctx

    async def deactivate(self) -> None:
        self._ctx = None

    def capabilities(self) -> dict[str, Any]:
        return {"name": self.NAME, "version": self.VERSION, "capabilities": self.CAPABILITIES}


def generate_plugin_manifest(
    name: str,
    version: str = "0.1.0",
    description: str = "",
    author: str = "",
    entry_point: str = "main",
    capabilities: list[str] | None = None,
    dependencies: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a ``plugin.json`` manifest dict."""
    return {
        "name": name,
        "version": version,
        "description": description,
        "author": author,
        "entry_point": entry_point,
        "capabilities": capabilities or [],
        "dependencies": dependencies or [],
        "min_core_version": "0.3.0",
    }


def scaffold_plugin(target_dir: str | Path, name: str, **kwargs: Any) -> Path:
    """Create a minimal plugin directory with manifest and entry module.

    Returns the path to the created directory.
    """
    root = Path(target_dir) / name
    root.mkdir(parents=True, exist_ok=True)

    manifest = generate_plugin_manifest(name, **kwargs)
    (root / "plugin.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    entry = kwargs.get("entry_point", "main")
    entry_file = root / f"{entry}.py"
    if not entry_file.exists():
        entry_file.write_text(
            f'''"""Plugin: {name}"""

from more_core.plugins.sdk import PluginBase, PluginContext


class Plugin(PluginBase):
    NAME = "{name}"
    VERSION = "{kwargs.get('version', '0.1.0')}"
    DESCRIPTION = "{kwargs.get('description', '')}"

    async def activate(self, ctx: PluginContext) -> None:
        await super().activate(ctx)
        # Register tools, replace layers, subscribe to events here.

    async def deactivate(self) -> None:
        await super().deactivate()
''',
            encoding="utf-8",
        )

    # README
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {name}\n\n{kwargs.get('description', 'A MoRE Core plugin.')}\n",
            encoding="utf-8",
        )

    return root
