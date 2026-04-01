"""Manifest-based plugin system.

Plugins contribute tools, hooks, and runtime constraints via a declarative
``plugin.json`` manifest. The registry aggregates contributions from all
enabled plugins and ensures global uniqueness of tool names.
"""

from deerflow.plugins.manifest import PluginManifest
from deerflow.plugins.registry import PluginRegistry

__all__ = ["PluginManifest", "PluginRegistry"]
