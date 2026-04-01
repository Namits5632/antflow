"""Tests for the hook governance layer (deerflow.hooks)."""

from deerflow.hooks.external import run_external_hook
from deerflow.hooks.python_hook import run_python_hook
from deerflow.hooks.runner import HookRunner
from deerflow.hooks.types import HookConfig, HookEvent, HookPayload, HookResult


class TestHookTypes:
    def test_event_count(self):
        assert len(HookEvent) == 5

    def test_result_allowed(self):
        r = HookResult.allowed("ok")
        assert not r.is_denied()
        assert r.message == "ok"

    def test_result_denied(self):
        r = HookResult.denied("blocked")
        assert r.is_denied()
        assert r.message == "blocked"

    def test_result_warned(self):
        r = HookResult.warned("caution")
        assert not r.is_denied()
        assert r.outcome == "warn"

    def test_config_matches_event(self):
        cfg = HookConfig(events=["pre_tool_use"])
        assert cfg.matches_event(HookEvent.PRE_TOOL_USE)
        assert not cfg.matches_event(HookEvent.POST_TOOL_USE)

    def test_config_matches_tool(self):
        cfg = HookConfig(tools=["bash"])
        assert cfg.matches_tool("bash")
        assert not cfg.matches_tool("read_file")

    def test_config_no_filter_matches_all(self):
        cfg = HookConfig()
        assert cfg.matches_event(HookEvent.POST_TOOL_USE)
        assert cfg.matches_tool("anything")


class TestExternalHook:
    def test_exit_0_allows(self):
        payload = HookPayload(event="pre_tool_use", tool_name="bash")
        result = run_external_hook("echo 'hook ok'", payload)
        assert not result.is_denied()
        assert result.message == "hook ok"

    def test_exit_2_denies(self):
        payload = HookPayload(event="pre_tool_use", tool_name="bash")
        result = run_external_hook("echo 'blocked' && exit 2", payload)
        assert result.is_denied()
        assert "blocked" in result.message

    def test_exit_1_warns(self):
        payload = HookPayload(event="pre_tool_use", tool_name="bash")
        result = run_external_hook("echo 'warning' && exit 1", payload)
        assert result.outcome == "warn"

    def test_env_vars_passed(self):
        payload = HookPayload(event="pre_tool_use", tool_name="bash")
        result = run_external_hook("echo $HOOK_TOOL_NAME", payload)
        assert result.message and "bash" in result.message


class TestPythonHook:
    def test_deny_hook(self):
        def hook(p: HookPayload) -> HookResult:
            return HookResult.denied(f"blocked {p.tool_name}")

        payload = HookPayload(event="pre_tool_use", tool_name="bash")
        result = run_python_hook(hook, payload)
        assert result.is_denied()

    def test_none_returns_allow(self):
        def hook(p: HookPayload) -> None:
            return None

        payload = HookPayload(event="pre_tool_use", tool_name="bash")
        result = run_python_hook(hook, payload)
        assert not result.is_denied()

    def test_exception_returns_warn(self):
        def hook(p: HookPayload) -> HookResult:
            raise RuntimeError("boom")

        payload = HookPayload(event="pre_tool_use", tool_name="bash")
        result = run_python_hook(hook, payload)
        assert result.outcome == "warn"


class TestHookRunner:
    def test_single_allow_hook(self):
        runner = HookRunner([HookConfig(command="echo 'ok'", events=["pre_tool_use"])])
        result = runner.run(HookEvent.PRE_TOOL_USE, "bash")
        assert not result.is_denied()

    def test_deny_short_circuits(self):
        runner = HookRunner(
            [
                HookConfig(command="echo 'first'", events=["pre_tool_use"]),
                HookConfig(command="echo 'nope' && exit 2", events=["pre_tool_use"]),
            ]
        )
        result = runner.run(HookEvent.PRE_TOOL_USE, "bash")
        assert result.is_denied()

    def test_tool_filter_skips_non_matching(self):
        runner = HookRunner(
            [
                HookConfig(command="echo 'nope' && exit 2", events=["pre_tool_use"], tools=["bash"]),
            ]
        )
        result = runner.run(HookEvent.PRE_TOOL_USE, "read_file")
        assert not result.is_denied()

    def test_from_config(self):
        runner = HookRunner.from_config(
            {
                "pre_tool_use": [{"command": "echo hi", "tools": ["bash"]}],
                "post_tool_use": [{"command": "echo done"}],
            }
        )
        assert len(runner._hooks) == 2

    def test_empty_runner_allows(self):
        runner = HookRunner()
        result = runner.run(HookEvent.PRE_TOOL_USE, "bash")
        assert not result.is_denied()
