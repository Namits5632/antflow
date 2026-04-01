"""Tests for the plugin system (deerflow.plugins)."""

from deerflow.plugins.manifest import PluginHooksDef, PluginManifest, PluginToolDef
from deerflow.plugins.registry import PluginRegistry


class TestPluginManifest:
    def test_create_manifest(self):
        m = PluginManifest(name="test", version="1.0.0")
        assert m.name == "test"
        assert m.enabled

    def test_from_dict_minimal(self):
        m = PluginManifest.from_dict({"name": "test"})
        assert m.name == "test"
        assert m.version == "0.0.0"

    def test_from_dict_with_tools(self):
        m = PluginManifest.from_dict(
            {
                "name": "test",
                "tools": [
                    {"name": "search", "command": "python search.py", "description": "Search"},
                ],
            }
        )
        assert len(m.tools) == 1
        assert m.tools[0].name == "search"

    def test_from_dict_invalid_tool_skipped(self):
        m = PluginManifest.from_dict(
            {
                "name": "test",
                "tools": [{"name": ""}],
            }
        )
        assert len(m.tools) == 0


class TestPluginRegistry:
    def test_register_success(self):
        registry = PluginRegistry()
        manifest = PluginManifest(
            name="test-plugin",
            tools=[PluginToolDef(name="custom_search", command="python search.py", description="Search")],
        )
        errors = registry.register(manifest)
        assert len(errors) == 0
        assert len(registry.aggregated_tools()) == 1

    def test_plugin_tool_conflict(self):
        registry = PluginRegistry()
        m1 = PluginManifest(
            name="plugin-a",
            tools=[PluginToolDef(name="search", command="a.py", description="A")],
        )
        m2 = PluginManifest(
            name="plugin-b",
            tools=[PluginToolDef(name="search", command="b.py", description="B")],
        )
        registry.register(m1)
        errors = registry.register(m2)
        assert len(errors) > 0
        assert "conflicts" in errors[0]

    def test_builtin_conflict(self):
        registry = PluginRegistry()
        m = PluginManifest(
            name="bad-plugin",
            tools=[PluginToolDef(name="bash", command="x", description="x")],
        )
        errors = registry.register(m, builtin_tool_names={"bash", "web_search"})
        assert len(errors) > 0
        assert "builtin" in errors[0]

    def test_hook_aggregation(self):
        registry = PluginRegistry()
        m = PluginManifest(
            name="hook-plugin",
            hooks=PluginHooksDef(pre_tool_use=["hooks/check.sh"]),
            root_path="/tmp/plugin",
        )
        registry.register(m)
        configs = registry.aggregated_hook_configs()
        assert len(configs) == 1
        assert "hooks/check.sh" in configs[0].command

    def test_tool_permission_specs(self):
        registry = PluginRegistry()
        m = PluginManifest(
            name="test",
            tools=[PluginToolDef(name="safe_read", command="x", description="x", required_permission="read_only")],
        )
        registry.register(m)
        specs = registry.tool_permission_specs()
        assert specs == [("safe_read", "read_only")]
