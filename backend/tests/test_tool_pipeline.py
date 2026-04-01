"""Tests for the tool execution pipeline (deerflow.tools.execution)."""

from deerflow.hooks.runner import HookRunner
from deerflow.hooks.types import HookConfig
from deerflow.permissions.mode import PermissionMode
from deerflow.permissions.policy import PermissionPolicy
from deerflow.tools.execution import ToolCallContext, ToolExecutionPipeline


def _echo_executor(name: str, inp: dict) -> str:
    return f"executed {name} with {inp}"


def _failing_executor(name: str, inp: dict) -> str:
    raise RuntimeError("boom")


class TestToolExecutionPipeline:
    def test_allow_mode_executes(self):
        pipeline = ToolExecutionPipeline(
            permission_policy=PermissionPolicy(active_mode=PermissionMode.ALLOW),
        )
        ctx = ToolCallContext(tool_name="bash", tool_input={"command": "ls"})
        result = pipeline.execute(ctx, _echo_executor)
        assert not result.is_error
        assert "executed bash" in result.output

    def test_permission_denied(self):
        pipeline = ToolExecutionPipeline(
            permission_policy=PermissionPolicy(
                active_mode=PermissionMode.READ_ONLY,
                tool_requirements={"bash": PermissionMode.DANGER_FULL_ACCESS},
            ),
        )
        ctx = ToolCallContext(tool_name="bash", tool_input={"command": "ls"})
        result = pipeline.execute(ctx, _echo_executor)
        assert result.is_error
        assert result.permission_denied

    def test_pre_hook_deny_blocks(self):
        pipeline = ToolExecutionPipeline(
            hook_runner=HookRunner(
                [
                    HookConfig(command="echo 'no' && exit 2", events=["pre_tool_use"]),
                ]
            ),
        )
        ctx = ToolCallContext(tool_name="bash", tool_input={})
        result = pipeline.execute(ctx, _echo_executor)
        assert result.is_error
        assert "Hook denied" in result.output

    def test_pre_hook_feedback_merged(self):
        pipeline = ToolExecutionPipeline(
            hook_runner=HookRunner(
                [
                    HookConfig(command="echo 'audit logged'", events=["pre_tool_use"]),
                ]
            ),
        )
        ctx = ToolCallContext(tool_name="bash", tool_input={})
        result = pipeline.execute(ctx, _echo_executor)
        assert not result.is_error
        assert "Pre-hook feedback" in result.output

    def test_executor_exception_handled(self):
        pipeline = ToolExecutionPipeline()
        ctx = ToolCallContext(tool_name="bash", tool_input={})
        result = pipeline.execute(ctx, _failing_executor)
        assert result.is_error
        assert "boom" in result.output
