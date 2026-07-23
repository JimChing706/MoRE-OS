"""Plugin discovery, loading, and lifecycle."""

from __future__ import annotations

import importlib.metadata as _ilm
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, List

from ..core.errors import PluginError
from .interface import PluginContext, PluginInterface, PluginMetadata

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime.orchestrator import MoRECore


class PluginManager:
    def __init__(self, plugin_dir: str | Path) -> None:
        self._plugin_dir = Path(plugin_dir)
        self._metadata: dict[str, PluginMetadata] = {}
        self._instances: dict[str, PluginInterface] = {}
        self._active: set[str] = set()

    # -- discovery ---------------------------------------------------------

    def discover(self) -> list[PluginMetadata]:
        if not self._plugin_dir.exists():
            return []
        results: list[PluginMetadata] = []
        for child in sorted(self._plugin_dir.iterdir()):
            manifest = child / "plugin.json"
            if child.is_dir() and manifest.exists():
                try:
                    md = self._read_manifest(manifest)
                    self._metadata[md.name] = md
                    results.append(md)
                except Exception as exc:  # pragma: no cover
                    raise PluginError(f"invalid plugin manifest at {manifest}: {exc}") from exc
        return results

    @staticmethod
    def _read_manifest(path: Path) -> PluginMetadata:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PluginMetadata(
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            dependencies=list(data.get("dependencies", [])),
            entry_point=data.get("entry_point", "main"),
            capabilities=list(data.get("capabilities", [])),
            min_core_version=data.get("min_core_version", "0.3.0"),
        )

    # -- loading -----------------------------------------------------------

    def load(self, name: str) -> PluginInterface:
        if name in self._instances:
            return self._instances[name]
        if name not in self._metadata:
            raise PluginError(f"unknown plugin: {name}")
        md = self._metadata[name]
        entry = self._plugin_dir / name / f"{md.entry_point}.py"
        if not entry.exists():
            raise PluginError(f"plugin entry missing: {entry}")

        # Create package module (__init__.py) to enable relative imports
        package_name = f"more_core_plugins.{name}"
        if package_name not in sys.modules:
            import types

            pkg = types.ModuleType(package_name)
            # Set package path to plugin directory for module resolution
            pkg.__path__ = [str(self._plugin_dir / name)]
            pkg.__file__ = str(self._plugin_dir / name / "__init__.py")
            sys.modules[package_name] = pkg

        # Full module name for entry point
        module_name = f"{package_name}.{md.entry_point}"
        spec = importlib.util.spec_from_file_location(module_name, entry)
        if spec is None or spec.loader is None:
            raise PluginError(f"cannot create spec for {entry}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        plugin_cls = getattr(module, "Plugin", None)
        if plugin_cls is None:
            raise PluginError(f"plugin {name} does not export class Plugin")
        instance = plugin_cls()
        if not isinstance(instance, PluginInterface):
            raise PluginError(f"plugin {name} does not implement PluginInterface")
        self._instances[name] = instance
        return instance

    # -- activation --------------------------------------------------------

    async def activate(self, name: str, core: "MoRECore") -> None:
        if name in self._active:
            return
        plugin = self.load(name)
        md = self._metadata[name]

        # Activate dependencies first (DFS; cycles unsupported).
        for dep in md.dependencies:
            if re.search(r"[><=!~]", dep):
                # pip-style package requirement — validate via importlib.metadata
                pkg_name = re.split(r"[><=!~\[]", dep)[0].strip()
                try:
                    _ilm.distribution(pkg_name)
                except _ilm.PackageNotFoundError:
                    raise PluginError(
                        f"plugin {name} depends on missing Python package {dep}; "
                        f"install it with: pip install '{dep}'"
                    )
            elif dep not in self._metadata:
                raise PluginError(f"plugin {name} depends on missing {dep}")
            elif dep not in self._active:
                await self.activate(dep, core)

        ctx = PluginContext(
            core=core,
            settings=core.settings,
            event_bus=core.event_bus,
            logger=core.logger,
        )
        await plugin.activate(ctx)
        self._active.add(name)

    async def deactivate(self, name: str) -> None:
        if name not in self._active:
            return
        # Reverse-dependency protection.
        for other, md in self._metadata.items():
            if other in self._active and name in md.dependencies:
                raise PluginError(f"cannot deactivate {name}: required by {other}")
        await self._instances[name].deactivate()
        self._active.remove(name)

    # -- query -------------------------------------------------------------

    def is_active(self, name: str) -> bool:
        return name in self._active

    def list(self) -> List[PluginMetadata]:
        return list(self._metadata.values())

    def active(self) -> List[PluginMetadata]:
        return [self._metadata[n] for n in self._active]
