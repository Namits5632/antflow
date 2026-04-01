"""Unified tool execution pipeline.

Stages (inspired by Claude Code's toolExecution.ts):
  1. Input validation
  2. Permission check
  3. PreToolUse hooks
  4. Actual execution
  5. PostToolUse hooks (or PostToolUseFailure)
  6. Merge hook feedback into result

This module provides both a standalone ``ToolExecutionPipeline`` for
programmatic use and a convenience function to build one from the current
``AppConfig``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from deerflow.hooks.runner import HookRunner
from deerflow.hooks.types import HookEvent, HookResult
from deerflow.permissions.mode import PermissionMode
from deerflow.permissions.policy import PermissionPolicy
from deerflow.permissions.prompter import PermissionPrompter

logger = logging.getLogger(__name__)


@dataclass
class ToolCallContext:
    """Normalised view of a tool call for pipeline processing."""

    tool_name: str
    tool_input: dict[str, Any]
    tool_call_id: str = "unknown"


@dataclass
class PipelineResult:
    """Outcome of a full pipeline execution."""

    output: str
    is_error: bool = False
    hook_messages: list[str] | None = None
    permission_denied: bool = False


class ToolExecutionPipeline:
    """Orchestrates validation -> permission -> hooks -> execution -> post-hooks."""

    def __init__(
        self,
        permission_policy: PermissionPolicy | None = None,
        hook_runner: HookRunner | None = None,
        prompter: PermissionPrompter | None = None,
    ):
        self.permission_policy = permission_policy or PermissionPolicy(active_mode=PermissionMode.ALLOW)
        self.hook_runner = hook_runner or HookRunner()
        self.prompter = prompter

    def execute(
        self,
        ctx: ToolCallContext,
        executor: Any,
    ) -> PipelineResult:
        """Run the full pipeline for a single tool call.

        Parameters
        ----------
        ctx:
            The normalised tool call.
        executor:
            A callable ``(tool_name, tool_input) -> str`` that performs the
            actual tool execution.
        """
        # --- 1. Permission check ---
        perm = self.permission_policy.authorize(ctx.tool_name, ctx.tool_input, self.prompter)
        if perm.is_denied():
            return PipelineResult(
                output=f"Permission denied: {perm.reason}",
                is_error=True,
                permission_denied=True,
            )

        # --- 2. Pre-tool hooks ---
        pre = self.hook_runner.run(
            HookEvent.PRE_TOOL_USE,
            ctx.tool_name,
            tool_input=ctx.tool_input,
        )
        if pre.is_denied():
            return PipelineResult(
                output=f"Hook denied: {pre.message}",
                is_error=True,
            )
        if pre.updated_input is not None:
            ctx = ToolCallContext(
                tool_name=ctx.tool_name,
                tool_input=pre.updated_input,
                tool_call_id=ctx.tool_call_id,
            )

        # --- 3. Execute ---
        try:
            output = executor(ctx.tool_name, ctx.tool_input)
        except Exception as exc:
            self.hook_runner.run(
                HookEvent.POST_TOOL_USE_FAILURE,
                ctx.tool_name,
                tool_input=ctx.tool_input,
                is_error=True,
            )
            return PipelineResult(
                output=f"Tool execution error: {exc}",
                is_error=True,
            )

        # --- 4. Post-tool hooks ---
        post = self.hook_runner.run(
            HookEvent.POST_TOOL_USE,
            ctx.tool_name,
            tool_input=ctx.tool_input,
            tool_output=output,
        )
        merged = _merge_feedback(output, pre, post)
        return PipelineResult(
            output=merged,
            is_error=post.is_denied(),
            hook_messages=[m for m in [pre.message, post.message] if m],
        )


def _merge_feedback(output: str, pre: HookResult, post: HookResult) -> str:
    """Append hook feedback to the tool output so the LLM can observe it."""
    parts = [output]
    if pre.message:
        parts.append(f"\n[Pre-hook feedback] {pre.message}")
    if post.message:
        parts.append(f"\n[Post-hook feedback] {post.message}")
    return "".join(parts)


def build_pipeline_from_config() -> ToolExecutionPipeline:
    """Convenience: build a pipeline from the current AppConfig singletons."""
    from deerflow.config.hooks_config import get_hooks_config
    from deerflow.config.permissions_config import get_permissions_config

    perms_cfg = get_permissions_config()
    hooks_cfg = get_hooks_config()

    mode_map = {
        "allow": PermissionMode.ALLOW,
        "prompt": PermissionMode.PROMPT,
        "danger_full_access": PermissionMode.DANGER_FULL_ACCESS,
        "workspace_write": PermissionMode.WORKSPACE_WRITE,
        "read_only": PermissionMode.READ_ONLY,
    }

    policy = PermissionPolicy(active_mode=mode_map.get(perms_cfg.mode, PermissionMode.ALLOW))
    for tool_name, mode_str in perms_cfg.tool_overrides.items():
        mode = mode_map.get(mode_str, PermissionMode.DANGER_FULL_ACCESS)
        policy = policy.with_tool_requirement(tool_name, mode)

    runner = HookRunner()
    if hooks_cfg.enabled:
        raw: dict = {}
        if hooks_cfg.pre_tool_use:
            raw["pre_tool_use"] = [h.model_dump(exclude_none=True) for h in hooks_cfg.pre_tool_use]
        if hooks_cfg.post_tool_use:
            raw["post_tool_use"] = [h.model_dump(exclude_none=True) for h in hooks_cfg.post_tool_use]
        if hooks_cfg.post_tool_use_failure:
            raw["post_tool_use_failure"] = [h.model_dump(exclude_none=True) for h in hooks_cfg.post_tool_use_failure]
        runner = HookRunner.from_config(raw)

    return ToolExecutionPipeline(permission_policy=policy, hook_runner=runner)
