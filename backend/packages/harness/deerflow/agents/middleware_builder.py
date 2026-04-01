"""Canonical middleware builder — single source of truth for chain assembly.

Both ``make_lead_agent`` (config-driven) and ``create_deerflow_agent``
(SDK-driven) delegate to this builder so the middleware order is consistent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from langchain.agents.middleware import AgentMiddleware

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class MiddlewareFeatures:
    """Feature flags controlling which middlewares are included."""

    sandbox: bool = True
    uploads: bool = True
    dangling_tool_call_patch: bool = True
    permissions: bool = True
    guardrail: bool = True
    hooks: bool = True
    sandbox_audit: bool = True
    tool_error_handling: bool = True
    summarization: bool = False
    compaction: bool = False
    plan_mode: bool = False
    token_usage: bool = False
    title: bool = True
    memory: bool = True
    vision: bool = False
    deferred_tool_filter: bool = False
    subagent_limit: bool = False
    loop_detection: bool = True
    clarification: bool = True

    lazy_init: bool = True
    agent_name: str | None = None
    model_name: str | None = None
    max_concurrent_subagents: int = 3

    custom_middlewares: list[AgentMiddleware] = field(default_factory=list)


def build_canonical_middleware_chain(features: MiddlewareFeatures) -> list[AgentMiddleware]:
    """Assemble the middleware chain in canonical order.

    Order:
      [0]  ThreadDataMiddleware
      [1]  UploadsMiddleware
      [2]  SandboxMiddleware
      [3]  DanglingToolCallMiddleware
      [4]  PermissionMiddleware          (NEW)
      [5]  GuardrailMiddleware
      [6]  HookMiddleware                (NEW)
      [7]  SandboxAuditMiddleware
      [8]  ToolErrorHandlingMiddleware
      [9]  SummarizationMiddleware       (optional)
      [10] CompactionMiddleware          (NEW, optional)
      [11] TodoMiddleware                (optional)
      [12] TokenUsageMiddleware          (optional)
      [13] TitleMiddleware
      [14] MemoryMiddleware
      [15] ViewImageMiddleware           (optional)
      [16] DeferredToolFilterMiddleware  (optional)
      [17] SubagentLimitMiddleware       (optional)
      [18] LoopDetectionMiddleware
      [19] [custom middlewares]
      [20] ClarificationMiddleware       (always last)
    """
    chain: list[AgentMiddleware] = []

    # --- [0-2] Sandbox infrastructure ---
    if features.sandbox:
        from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
        from deerflow.sandbox.middleware import SandboxMiddleware

        chain.append(ThreadDataMiddleware(lazy_init=features.lazy_init))

        if features.uploads:
            from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware

            chain.append(UploadsMiddleware())

        chain.append(SandboxMiddleware(lazy_init=features.lazy_init))

    # --- [3] DanglingToolCallMiddleware ---
    if features.dangling_tool_call_patch:
        from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

        chain.append(DanglingToolCallMiddleware())

    # --- [4] PermissionMiddleware (NEW) ---
    if features.permissions:
        _maybe_add_permission_middleware(chain)

    # --- [5] GuardrailMiddleware ---
    if features.guardrail:
        _maybe_add_guardrail_middleware(chain)

    # --- [6] HookMiddleware (NEW) ---
    if features.hooks:
        _maybe_add_hook_middleware(chain)

    # --- [7] SandboxAuditMiddleware ---
    if features.sandbox_audit:
        from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware

        chain.append(SandboxAuditMiddleware())

    # --- [8] ToolErrorHandlingMiddleware ---
    if features.tool_error_handling:
        from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware

        chain.append(ToolErrorHandlingMiddleware())

    # --- [9] SummarizationMiddleware ---
    if features.summarization:
        _maybe_add_summarization_middleware(chain)

    # --- [10] CompactionMiddleware (NEW) ---
    if features.compaction:
        _maybe_add_compaction_middleware(chain)

    # --- [11] TodoMiddleware ---
    if features.plan_mode:
        from deerflow.agents.middlewares.todo_middleware import TodoMiddleware

        chain.append(TodoMiddleware())

    # --- [12] TokenUsageMiddleware ---
    if features.token_usage:
        from deerflow.agents.middlewares.token_usage_middleware import TokenUsageMiddleware

        chain.append(TokenUsageMiddleware())

    # --- [13] TitleMiddleware ---
    if features.title:
        from deerflow.agents.middlewares.title_middleware import TitleMiddleware

        chain.append(TitleMiddleware())

    # --- [14] MemoryMiddleware ---
    if features.memory:
        from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware

        chain.append(MemoryMiddleware(agent_name=features.agent_name))

    # --- [15] ViewImageMiddleware ---
    if features.vision:
        from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware

        chain.append(ViewImageMiddleware())

    # --- [16] DeferredToolFilterMiddleware ---
    if features.deferred_tool_filter:
        from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

        chain.append(DeferredToolFilterMiddleware())

    # --- [17] SubagentLimitMiddleware ---
    if features.subagent_limit:
        from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware

        chain.append(SubagentLimitMiddleware(max_concurrent=features.max_concurrent_subagents))

    # --- [18] LoopDetectionMiddleware ---
    if features.loop_detection:
        from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

        chain.append(LoopDetectionMiddleware())

    # --- [19] Custom middlewares ---
    for mw in features.custom_middlewares:
        chain.append(mw)

    # --- [20] ClarificationMiddleware (always last) ---
    if features.clarification:
        from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

        chain.append(ClarificationMiddleware())

    return chain


# ---------------------------------------------------------------------------
# Internal helpers for conditional middleware creation
# ---------------------------------------------------------------------------


def _maybe_add_permission_middleware(chain: list[AgentMiddleware]) -> None:
    """Add PermissionMiddleware if permissions are configured and not in allow-all mode."""
    from deerflow.config.permissions_config import get_permissions_config
    from deerflow.permissions.middleware import PermissionMiddleware
    from deerflow.permissions.mode import PermissionMode
    from deerflow.permissions.policy import PermissionPolicy

    cfg = get_permissions_config()
    if not cfg.enabled:
        return

    mode_map = {
        "allow": PermissionMode.ALLOW,
        "prompt": PermissionMode.PROMPT,
        "danger_full_access": PermissionMode.DANGER_FULL_ACCESS,
        "workspace_write": PermissionMode.WORKSPACE_WRITE,
        "read_only": PermissionMode.READ_ONLY,
    }
    active = mode_map.get(cfg.mode, PermissionMode.ALLOW)

    if active == PermissionMode.ALLOW and not cfg.tool_overrides:
        return

    policy = PermissionPolicy(active_mode=active)
    for tool_name, mode_str in cfg.tool_overrides.items():
        mode = mode_map.get(mode_str, PermissionMode.DANGER_FULL_ACCESS)
        policy = policy.with_tool_requirement(tool_name, mode)

    chain.append(PermissionMiddleware(policy))


def _maybe_add_guardrail_middleware(chain: list[AgentMiddleware]) -> None:
    """Add GuardrailMiddleware if a provider is configured."""
    import inspect

    from deerflow.config.guardrails_config import get_guardrails_config
    from deerflow.guardrails.middleware import GuardrailMiddleware
    from deerflow.reflection import resolve_variable

    cfg = get_guardrails_config()
    if not cfg.enabled or not cfg.provider:
        return

    provider_cls = resolve_variable(cfg.provider.use)
    kwargs = dict(cfg.provider.config) if cfg.provider.config else {}
    if "framework" not in kwargs:
        try:
            sig = inspect.signature(provider_cls.__init__)
            if "framework" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                kwargs["framework"] = "deerflow"
        except (ValueError, TypeError):
            pass
    provider = provider_cls(**kwargs)
    chain.append(GuardrailMiddleware(provider, fail_closed=cfg.fail_closed, passport=cfg.passport))


def _maybe_add_hook_middleware(chain: list[AgentMiddleware]) -> None:
    """Add HookMiddleware if hooks are configured and enabled."""
    from deerflow.config.hooks_config import get_hooks_config
    from deerflow.hooks.middleware import HookMiddleware
    from deerflow.hooks.runner import HookRunner

    cfg = get_hooks_config()
    if not cfg.enabled:
        return

    raw: dict = {}
    if cfg.pre_tool_use:
        raw["pre_tool_use"] = [h.model_dump(exclude_none=True) for h in cfg.pre_tool_use]
    if cfg.post_tool_use:
        raw["post_tool_use"] = [h.model_dump(exclude_none=True) for h in cfg.post_tool_use]
    if cfg.post_tool_use_failure:
        raw["post_tool_use_failure"] = [h.model_dump(exclude_none=True) for h in cfg.post_tool_use_failure]

    if raw:
        runner = HookRunner.from_config(raw)
        chain.append(HookMiddleware(runner))


def _maybe_add_summarization_middleware(chain: list[AgentMiddleware]) -> None:
    """Add SummarizationMiddleware from config if enabled."""
    from langchain.agents.middleware import SummarizationMiddleware

    from deerflow.config.summarization_config import get_summarization_config
    from deerflow.models import create_chat_model

    cfg = get_summarization_config()
    if not cfg.enabled:
        return

    trigger = None
    if cfg.trigger is not None:
        if isinstance(cfg.trigger, list):
            trigger = [t.to_tuple() for t in cfg.trigger]
        else:
            trigger = cfg.trigger.to_tuple()

    keep = cfg.keep.to_tuple()
    model = create_chat_model(name=cfg.model_name, thinking_enabled=False) if cfg.model_name else create_chat_model(thinking_enabled=False)

    kwargs = {"model": model, "trigger": trigger, "keep": keep}
    if cfg.trim_tokens_to_summarize is not None:
        kwargs["trim_tokens_to_summarize"] = cfg.trim_tokens_to_summarize
    if cfg.summary_prompt is not None:
        kwargs["summary_prompt"] = cfg.summary_prompt

    chain.append(SummarizationMiddleware(**kwargs))


def _maybe_add_compaction_middleware(chain: list[AgentMiddleware]) -> None:
    """Add CompactionMiddleware if context compaction is configured."""
    try:
        from deerflow.context.middleware import CompactionMiddleware

        chain.append(CompactionMiddleware())
    except ImportError:
        logger.debug("CompactionMiddleware not yet available; skipping")
