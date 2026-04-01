"""Comprehensive functional tests for all DeerFlow renovation modules."""
import os
import sys
import json
import tempfile
import textwrap

PASS = 0
FAIL = 0

def report(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    mark = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {name}{suffix}")


print("=" * 60)
print("  TEST SUITE: DeerFlow Renovation Modules")
print("=" * 60)

# ====================================================================
# 1. Permissions Module
# ====================================================================
print("\n--- 1. Permissions Module ---")

from deerflow.permissions.mode import PermissionMode
from deerflow.permissions.policy import PermissionPolicy, PermissionOutcome
from deerflow.permissions.prompter import AutoAllowPrompter, AutoDenyPrompter

report("PermissionMode ordering",
       PermissionMode.READ_ONLY < PermissionMode.WORKSPACE_WRITE < PermissionMode.ALLOW,
       f"READ_ONLY({PermissionMode.READ_ONLY}) < WORKSPACE_WRITE({PermissionMode.WORKSPACE_WRITE}) < ALLOW({PermissionMode.ALLOW})")

policy_allow = PermissionPolicy(active_mode=PermissionMode.ALLOW)
out = policy_allow.authorize("bash")
report("ALLOW mode permits everything", out.allowed)

policy_ro = PermissionPolicy(
    active_mode=PermissionMode.READ_ONLY,
    tool_requirements={"read_file": PermissionMode.READ_ONLY, "bash": PermissionMode.DANGER_FULL_ACCESS},
)
out_read = policy_ro.authorize("read_file")
report("READ_ONLY mode permits read tools", out_read.allowed)

out_bash = policy_ro.authorize("bash")
report("READ_ONLY mode blocks bash", out_bash.is_denied(),
       f"reason={out_bash.reason}")

policy_prompt = PermissionPolicy(
    active_mode=PermissionMode.PROMPT,
    tool_requirements={"bash": PermissionMode.DANGER_FULL_ACCESS},
)
out_auto_allow = policy_prompt.authorize("bash", prompter=AutoAllowPrompter())
report("PROMPT mode: PROMPT(40) >= DANGER(30) → auto-allow", out_auto_allow.allowed)

policy_prompt_high = PermissionPolicy(
    active_mode=PermissionMode.PROMPT,
    tool_requirements={"nuke": PermissionMode.ALLOW},
)
out_prompt_allow = policy_prompt_high.authorize("nuke", prompter=AutoAllowPrompter())
report("PROMPT mode + ALLOW-required tool + AutoAllowPrompter → allow", out_prompt_allow.allowed)

out_prompt_deny = policy_prompt_high.authorize("nuke", prompter=AutoDenyPrompter())
report("PROMPT mode + ALLOW-required tool + AutoDenyPrompter → deny", out_prompt_deny.is_denied())

p2 = policy_allow.with_tool_requirement("new_tool", PermissionMode.WORKSPACE_WRITE)
report("with_tool_requirement creates new policy (immutability)",
       "new_tool" in p2.tool_requirements and "new_tool" not in policy_allow.tool_requirements)

unknown_default = policy_ro.required_mode_for("unknown_tool")
report("Unknown tool defaults to DANGER_FULL_ACCESS",
       unknown_default == PermissionMode.DANGER_FULL_ACCESS)


# ====================================================================
# 2. Hooks Module
# ====================================================================
print("\n--- 2. Hooks Module ---")

from deerflow.hooks.types import HookEvent, HookResult, HookConfig, HookPayload
from deerflow.hooks.runner import HookRunner
from deerflow.hooks.external import run_external_hook
from deerflow.hooks.python_hook import run_python_hook

report("HookEvent enumeration",
       len(HookEvent) == 5,
       f"events={[e.name for e in HookEvent]}")

r_allow = HookResult.allowed("test message")
report("HookResult.allowed()", not r_allow.is_denied() and r_allow.message == "test message")

r_deny = HookResult.denied("blocked")
report("HookResult.denied()", r_deny.is_denied() and r_deny.message == "blocked")

r_warn = HookResult.warned("caution")
report("HookResult.warned()", not r_warn.is_denied() and r_warn.outcome == "warn")

cfg_match = HookConfig(events=["pre_tool_use"], tools=["bash"])
report("HookConfig.matches_event(PRE_TOOL_USE)", cfg_match.matches_event(HookEvent.PRE_TOOL_USE))
report("HookConfig.matches_event(POST_TOOL_USE) → False", not cfg_match.matches_event(HookEvent.POST_TOOL_USE))
report("HookConfig.matches_tool('bash')", cfg_match.matches_tool("bash"))
report("HookConfig.matches_tool('read_file') → False", not cfg_match.matches_tool("read_file"))

cfg_all = HookConfig()
report("HookConfig(no filter) matches any event", cfg_all.matches_event(HookEvent.POST_TOOL_USE))
report("HookConfig(no filter) matches any tool", cfg_all.matches_tool("anything"))

# Test external hook: exit 0 → allow
payload = HookPayload(event="pre_tool_use", tool_name="bash", tool_input={"command": "ls"})
result_ext = run_external_hook("echo 'hook ok'", payload)
report("External hook exit 0 → allow", not result_ext.is_denied(),
       f"outcome={result_ext.outcome}, msg={result_ext.message!r}")

# Test external hook: exit 2 → deny
result_deny = run_external_hook("echo 'blocked by policy' && exit 2", payload)
report("External hook exit 2 → deny", result_deny.is_denied(),
       f"msg={result_deny.message!r}")

# Test external hook: exit 1 → warn
result_warn = run_external_hook("echo 'warning' && exit 1", payload)
report("External hook exit 1 → warn", result_warn.outcome == "warn",
       f"msg={result_warn.message!r}")

# Test external hook: env vars are passed
result_env = run_external_hook("echo $HOOK_TOOL_NAME", payload)
report("External hook receives HOOK_TOOL_NAME env",
       result_env.message and "bash" in result_env.message,
       f"stdout={result_env.message!r}")

# Test Python hook
def my_hook(p: HookPayload) -> HookResult:
    return HookResult.denied(f"python hook blocked {p.tool_name}")

result_py = run_python_hook(my_hook, payload)
report("Python hook callable → deny", result_py.is_denied(),
       f"msg={result_py.message!r}")

def my_allow_hook(p: HookPayload) -> None:
    return None

result_py_none = run_python_hook(my_allow_hook, payload)
report("Python hook returning None → allow", not result_py_none.is_denied())

# HookRunner integration
runner = HookRunner([
    HookConfig(command="echo 'audit log'", events=["pre_tool_use"]),
])
runner_result = runner.run(HookEvent.PRE_TOOL_USE, "bash")
report("HookRunner with 1 allow hook → allow", not runner_result.is_denied())

runner_deny = HookRunner([
    HookConfig(command="echo 'ok'", events=["pre_tool_use"]),
    HookConfig(command="echo 'nope' && exit 2", events=["pre_tool_use"]),
])
runner_deny_result = runner_deny.run(HookEvent.PRE_TOOL_USE, "bash")
report("HookRunner deny short-circuits", runner_deny_result.is_denied(),
       f"msg={runner_deny_result.message!r}")

runner_filtered = HookRunner([
    HookConfig(command="echo 'nope' && exit 2", events=["pre_tool_use"], tools=["bash"]),
])
runner_ok = runner_filtered.run(HookEvent.PRE_TOOL_USE, "read_file")
report("HookRunner tool filter: non-matching tool → allow", not runner_ok.is_denied())

runner_config = HookRunner.from_config({
    "pre_tool_use": [{"command": "echo hi", "tools": ["bash"]}],
    "post_tool_use": [{"command": "echo done"}],
})
report("HookRunner.from_config loads entries",
       len(runner_config._hooks) == 2)


# ====================================================================
# 3. Tool Execution Pipeline
# ====================================================================
print("\n--- 3. Tool Execution Pipeline ---")

from deerflow.tools.execution import ToolExecutionPipeline, ToolCallContext, PipelineResult

def dummy_executor(name, inp):
    return f"executed {name} with {inp}"

pipeline = ToolExecutionPipeline(
    permission_policy=PermissionPolicy(active_mode=PermissionMode.ALLOW),
    hook_runner=HookRunner(),
)
ctx = ToolCallContext(tool_name="bash", tool_input={"command": "ls"})
result = pipeline.execute(ctx, dummy_executor)
report("Pipeline ALLOW mode executes", not result.is_error,
       f"output={result.output[:50]!r}")

pipeline_ro = ToolExecutionPipeline(
    permission_policy=PermissionPolicy(
        active_mode=PermissionMode.READ_ONLY,
        tool_requirements={"bash": PermissionMode.DANGER_FULL_ACCESS},
    ),
)
result_denied = pipeline_ro.execute(ctx, dummy_executor)
report("Pipeline READ_ONLY blocks bash", result_denied.is_error and result_denied.permission_denied,
       f"output={result_denied.output[:80]!r}")

pipeline_hook = ToolExecutionPipeline(
    permission_policy=PermissionPolicy(active_mode=PermissionMode.ALLOW),
    hook_runner=HookRunner([
        HookConfig(command="echo 'audit' && exit 0", events=["pre_tool_use"]),
    ]),
)
result_hooked = pipeline_hook.execute(ctx, dummy_executor)
report("Pipeline with pre-hook: allow + feedback merged",
       not result_hooked.is_error,
       f"output snippet={result_hooked.output[:80]!r}")

pipeline_deny_hook = ToolExecutionPipeline(
    permission_policy=PermissionPolicy(active_mode=PermissionMode.ALLOW),
    hook_runner=HookRunner([
        HookConfig(command="echo 'no way' && exit 2", events=["pre_tool_use"]),
    ]),
)
result_hook_deny = pipeline_deny_hook.execute(ctx, dummy_executor)
report("Pipeline pre-hook deny blocks execution", result_hook_deny.is_error,
       f"output={result_hook_deny.output[:60]!r}")

def failing_executor(name, inp):
    raise RuntimeError("boom")

pipeline_err = ToolExecutionPipeline()
result_err = pipeline_err.execute(ctx, failing_executor)
report("Pipeline handles executor exception", result_err.is_error,
       f"output={result_err.output[:60]!r}")


# ====================================================================
# 4. Specialized Agents
# ====================================================================
print("\n--- 4. Specialized Agents ---")

from deerflow.subagents.builtins.explore_agent import EXPLORE_AGENT_CONFIG
from deerflow.subagents.builtins.plan_agent import PLAN_AGENT_CONFIG
from deerflow.subagents.builtins.verification_agent import VERIFICATION_AGENT_CONFIG

report("Explore agent name", EXPLORE_AGENT_CONFIG.name == "explore")
report("Explore agent has system prompt", bool(EXPLORE_AGENT_CONFIG.system_prompt))
report("Explore agent has disallowed_tools",
       EXPLORE_AGENT_CONFIG.disallowed_tools is not None and len(EXPLORE_AGENT_CONFIG.disallowed_tools) > 0,
       f"disallowed={EXPLORE_AGENT_CONFIG.disallowed_tools}")

report("Plan agent name", PLAN_AGENT_CONFIG.name == "plan")
report("Plan agent has system prompt", bool(PLAN_AGENT_CONFIG.system_prompt))

report("Verification agent name", VERIFICATION_AGENT_CONFIG.name == "verification")
report("Verification agent has system prompt", bool(VERIFICATION_AGENT_CONFIG.system_prompt))


# ====================================================================
# 5. Prompt Builder
# ====================================================================
print("\n--- 5. Prompt Builder ---")

from deerflow.prompts import SystemPromptBuilder
from deerflow.prompts.sections import SYSTEM_PROMPT_DYNAMIC_BOUNDARY

builder = SystemPromptBuilder(agent_name="TestAgent")
prompt = builder.build()
report("Basic build produces non-empty prompt", len(prompt) > 100,
       f"length={len(prompt)}")
report("Prompt contains dynamic boundary", SYSTEM_PROMPT_DYNAMIC_BOUNDARY in prompt)

prompt_full = (
    SystemPromptBuilder(agent_name="TestAgent")
    .with_memory("[Memory] user prefers Chinese")
    .with_skills("[Skills] web_search, bash")
    .with_environment(cwd="/tmp/test", date_str="2026-04-01")
    .with_specialized_agents(verification=True, explore=True, plan=True)
    .build()
)
report("Full build includes memory section", "[Memory] user prefers Chinese" in prompt_full)
report("Full build includes skills section", "[Skills] web_search, bash" in prompt_full)
report("Full build includes environment info", "/tmp/test" in prompt_full)

idx_boundary = prompt_full.index(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
idx_memory = prompt_full.index("[Memory]")
report("Dynamic sections come AFTER boundary",
       idx_memory > idx_boundary,
       f"boundary@{idx_boundary}, memory@{idx_memory}")


# ====================================================================
# 6. Context Compaction
# ====================================================================
print("\n--- 6. Context Compaction ---")

from deerflow.context import CompactionEngine, CompactionConfig, TokenBudget
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

budget = TokenBudget(max_tokens=1000)
report("TokenBudget initial", budget.current == 0 and budget.remaining == 1000)
budget.add_text("Hello world!")
report("TokenBudget after add_text", budget.current > 0,
       f"current={budget.current}, remaining={budget.remaining}")
report("TokenBudget should_compact (low usage)", not budget.should_compact(threshold=0.8))
budget.set_estimate(900)
report("TokenBudget should_compact (high usage)", budget.should_compact(threshold=0.8))

engine = CompactionEngine(CompactionConfig(
    max_estimated_tokens=20,
    preserve_recent_messages=2,
))

msgs = [
    HumanMessage(content="Please analyze /src/main.py"),
    AIMessage(content="I'll read that file for you."),
    HumanMessage(content="Also look at /src/utils.py"),
    AIMessage(content="Done. The file has utility functions."),
    HumanMessage(content="Now write tests"),
    AIMessage(content="Writing tests now."),
    HumanMessage(content="Show me the results"),
    AIMessage(content="All tests passed."),
]

report("should_compact with 8 messages",
       engine.should_compact(msgs),
       f"estimated_tokens={engine.estimate_tokens(msgs)}")

result = engine.compact(msgs)
report("compact preserves recent messages",
       result.preserved_count == 2,
       f"preserved={result.preserved_count}, removed={result.removed_count}")
report("compact produces summary",
       len(result.summary_text) > 0,
       f"summary_len={len(result.summary_text)}")
report("compact summary mentions user requests",
       "analyze" in result.summary_text.lower() or "User requests" in result.summary_text)
report("compact summary mentions paths",
       "/src/main.py" in result.summary_text or "Key paths" in result.summary_text)

short_msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
result_short = engine.compact(short_msgs)
report("compact preserves short conversations",
       result_short.preserved_count == 2 and result_short.removed_count == 0)


# ====================================================================
# 7. Plugin System
# ====================================================================
print("\n--- 7. Plugin System ---")

from deerflow.plugins.manifest import PluginManifest, PluginToolDef, PluginHooksDef
from deerflow.plugins.registry import PluginRegistry

manifest = PluginManifest(
    name="test-plugin",
    version="0.1.0",
    description="Test plugin",
    root_path="/tmp/test-plugin",
    tools=[
        PluginToolDef(name="custom_search", command="python search.py", description="Search"),
        PluginToolDef(name="custom_lint", command="python lint.py", description="Lint"),
    ],
    hooks=PluginHooksDef(pre_tool_use=["hooks/pre.sh"]),
)

report("PluginManifest creation", manifest.name == "test-plugin")
report("PluginManifest has 2 tools", len(manifest.tools) == 2)

registry = PluginRegistry()
errors = registry.register(manifest)
report("PluginRegistry registers successfully", len(errors) == 0)

tools = registry.aggregated_tools()
report("Registry aggregated_tools", len(tools) == 2,
       f"tools={[t.name for t in tools]}")

hook_configs = registry.aggregated_hook_configs()
report("Registry aggregated_hook_configs",
       len(hook_configs) == 1,
       f"hooks={[h.command for h in hook_configs]}")

manifest2 = PluginManifest(
    name="conflict-plugin",
    version="0.1.0",
    description="Conflicting plugin",
    root_path="/tmp/conflict",
    tools=[PluginToolDef(name="custom_search", command="python x.py", description="dup")],
)
errors2 = registry.register(manifest2)
report("Registry detects tool name conflicts", len(errors2) > 0,
       f"errors={errors2}")

errors3 = registry.register(
    PluginManifest(name="builtin-conflict", version="0.1.0", description="x", root_path="/tmp/x",
                   tools=[PluginToolDef(name="bash", command="x", description="x")]),
    builtin_tool_names={"bash", "web_search"},
)
report("Registry detects builtin name conflicts", len(errors3) > 0,
       f"errors={errors3}")


# ====================================================================
# 8. Middleware Builder
# ====================================================================
print("\n--- 8. Middleware Builder ---")

from deerflow.agents.middleware_builder import build_canonical_middleware_chain, MiddlewareFeatures

features_minimal = MiddlewareFeatures(
    sandbox=False, uploads=False, dangling_tool_call_patch=False,
    permissions=False, guardrail=False, hooks=False,
    sandbox_audit=False, tool_error_handling=False,
    title=False, memory=False, loop_detection=False, clarification=False,
)
chain_empty = build_canonical_middleware_chain(features_minimal)
report("Minimal features → empty chain", len(chain_empty) == 0)

features_perms_hooks = MiddlewareFeatures(
    sandbox=False, uploads=False, dangling_tool_call_patch=False,
    permissions=False, guardrail=False, hooks=False,
    sandbox_audit=False, tool_error_handling=True,
    title=False, memory=False, loop_detection=True, clarification=True,
)
chain_basic = build_canonical_middleware_chain(features_perms_hooks)
chain_names = [type(m).__name__ for m in chain_basic]
report("Basic chain includes ToolErrorHandling + LoopDetection + Clarification",
       len(chain_basic) == 3,
       f"middlewares={chain_names}")

report("MiddlewareFeatures dataclass has all new fields",
       hasattr(features_minimal, 'permissions') and
       hasattr(features_minimal, 'hooks') and
       hasattr(features_minimal, 'compaction'),
       "permissions, hooks, compaction fields present")


# ====================================================================
# Summary
# ====================================================================
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"  RESULTS: {PASS}/{total} passed, {FAIL} failed")
if FAIL == 0:
    print("  ALL TESTS PASSED!")
else:
    print(f"  {FAIL} TEST(S) FAILED — see above for details")
print("=" * 60)

sys.exit(0 if FAIL == 0 else 1)
