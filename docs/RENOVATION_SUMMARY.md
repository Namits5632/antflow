# DeerFlow 深度改造全面总结

## 一、项目概述

### 1.1 改造目标

将 Claude Code（泄露源码经 claw-code 项目重构）中被验证有效的 **Agent Operating System** 级设计引入 DeerFlow 2.0，使其从一个"agent harness"升级为具备完整治理能力的 agent 操作系统。

### 1.2 参考来源

| 来源 | 用途 |
|------|------|
| `claw-code` 项目 | Claude Code 泄露源码的 Python/Rust 重构版，提供了权限、Hook、Prompt、Compaction 等核心实现参考 |
| 《Claude Code 源码深度研究报告》 | 对 Claude Code 架构的系统分析，提炼了 10 大核心设计模式 |
| `deer-flow` 原始代码 | ByteDance 开源 agent 框架，提供了 LangGraph/中间件/子 agent/沙箱/Guardrail 基础 |

### 1.3 改造原则

- **非侵入**：所有新功能作为独立模块添加，不修改现有核心逻辑
- **默认无感**：权限默认 `allow`（全放行）、Hook 默认无条目（空管道），老用户零感知
- **渐进启用**：通过 `config.yaml` 配置即可逐步开启权限收紧、Hook 审计等治理能力
- **向后兼容**：`config_version` 从 4 升到 5，`make config-upgrade` 可平滑迁移

---

## 二、改造模块全景

### 架构纵览

```
用户请求
  │
  ▼
┌─────────────────────────────────────────────────┐
│             Middleware Chain (21 位点)            │
│                                                  │
│  [0-2] Sandbox 基础设施                          │
│  [3]   DanglingToolCall 修复                     │
│  [4]   PermissionMiddleware        ← NEW         │
│  [5]   GuardrailMiddleware                       │
│  [6]   HookMiddleware              ← NEW         │
│  [7]   SandboxAuditMiddleware                    │
│  [8]   ToolErrorHandling                         │
│  [9]   Summarization                             │
│  [10]  CompactionMiddleware        ← NEW         │
│  [11-20] Title/Memory/Vision/Loop/Clarification  │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│          Tool Execution Pipeline                 │
│                                                  │
│  Permission Check → Pre-Hook → Execute →         │
│  Post-Hook → Merge Feedback                      │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│          SystemPromptBuilder                     │
│                                                  │
│  [Static prefix - cacheable]                     │
│  ── CACHE BOUNDARY ──                            │
│  [Dynamic suffix - per session]                  │
└─────────────────────────────────────────────────┘
```

### 模块清单

| # | 模块 | 包路径 | 核心类 | 灵感来源 |
|---|------|--------|--------|----------|
| 1 | 分层权限模型 | `deerflow/permissions/` | `PermissionMode`, `PermissionPolicy`, `PermissionPrompter` | `claw-code/runtime/permissions.rs` |
| 2 | Hook 治理层 | `deerflow/hooks/` | `HookRunner`, `HookEvent`, `HookResult` | `claw-code/runtime/hooks.rs` |
| 3 | 工具执行流水线 | `deerflow/tools/execution.py` | `ToolExecutionPipeline`, `ToolCallContext`, `PipelineResult` | `claw-code/runtime/conversation.rs` |
| 4 | 统一中间件装配 | `deerflow/agents/middleware_builder.py` | `MiddlewareFeatures`, `build_canonical_middleware_chain` | 消除 factory vs make_lead_agent 双路径不一致 |
| 5 | 专精 Agent | `deerflow/subagents/builtins/` | Explore / Plan / Verification Agent | Claude Code 的 agent specialization + fork 语义 |
| 6 | 模块化 Prompt | `deerflow/prompts/` | `SystemPromptBuilder` | `claw-code/runtime/prompt.rs` |
| 7 | 上下文压缩引擎 | `deerflow/context/` | `CompactionEngine`, `TokenBudget` | `claw-code/runtime/compact.rs` |
| 8 | 插件系统 | `deerflow/plugins/` | `PluginManifest`, `PluginRegistry` | `claw-code/plugins/` |

---

## 三、各模块详细说明

### 3.1 分层权限模型

**核心设计**：5 级有序权限层级，高级别自动包含低级别权限。

```
READ_ONLY (10) < WORKSPACE_WRITE (20) < DANGER_FULL_ACCESS (30) < PROMPT (40) < ALLOW (50)
```

**工作流程**：
1. 每个工具声明所需的最低权限级别（如 `bash` → `DANGER_FULL_ACCESS`）
2. 会话有一个当前 mode（如 `WORKSPACE_WRITE`）
3. 若 session mode >= tool requirement → 自动放行
4. 若 mode == PROMPT 且权限不足 → 交由 `PermissionPrompter` 决策（支持 CLI/HTTP/WebSocket）
5. 否则 → 拒绝，返回结构化错误

**安全默认值**：未注册工具默认要求 `DANGER_FULL_ACCESS`，防止遗漏工具被低权限放行。

**文件清单**：
- `permissions/mode.py` — `PermissionMode` IntEnum
- `permissions/policy.py` — `PermissionPolicy` + `PermissionOutcome`
- `permissions/prompter.py` — `PermissionPrompter` ABC + `AutoAllowPrompter` / `AutoDenyPrompter`
- `permissions/middleware.py` — `PermissionMiddleware`
- `config/permissions_config.py` — `PermissionsConfig` Pydantic 模型

### 3.2 Hook 治理层

**核心设计**：可编程的工具调用拦截点，支持审计、输入修改、执行拒绝和反馈注入。

**5 种事件**：`PRE_TOOL_USE` / `POST_TOOL_USE` / `POST_TOOL_USE_FAILURE` / `SUBAGENT_START` / `SUBAGENT_END`

**两种 Hook 类型**：

| 类型 | 配置方式 | 执行方式 |
|------|----------|----------|
| 外部进程 | `command: "python check.py"` | 子进程, stdin=JSON, exit code 语义 |
| Python 函数 | `use: "module:func"` | 直接调用, 返回 `HookResult` |

**外部进程协议（兼容 Claude Code）**：
- stdin: JSON `{event, tool_name, input, output, is_error}`
- 环境变量: `HOOK_EVENT`, `HOOK_TOOL_NAME`, `HOOK_TOOL_INPUT`
- exit 0 → allow（stdout 为可选消息）
- exit 2 → deny（stdout 为拒绝原因）
- 其他 → warn（非阻塞，仅记录）

**执行语义**：HookRunner 顺序执行匹配的 hook 列表；deny 立即短路。

**文件清单**：
- `hooks/types.py` — `HookEvent`, `HookResult`, `HookConfig`, `HookPayload`
- `hooks/runner.py` — `HookRunner`
- `hooks/external.py` — 外部进程执行器
- `hooks/python_hook.py` — Python 函数执行器
- `hooks/middleware.py` — `HookMiddleware`
- `config/hooks_config.py` — `HooksConfig` Pydantic 模型

### 3.3 工具执行流水线

**核心设计**：将工具执行从"直接调用"升级为 5 阶段流水线。

```
Permission Check → PreToolUse Hooks → Execute → PostToolUse Hooks → Merge Feedback
       ↓ deny          ↓ deny           ↓ error      ↓ deny
    结构化错误        结构化错误       PostFailure   结构化错误
                                        Hooks
```

- 每个阶段的 deny 都生成结构化 error 信息，LLM 可感知并据此调整策略
- Pre-hook 可修改工具输入（`updated_input`），后续阶段使用修改后的输入
- Hook 反馈通过 `[Pre-hook feedback]` / `[Post-hook feedback]` 标记合并到输出
- `build_pipeline_from_config()` 从 `config.yaml` 构建完整流水线

### 3.4 统一中间件装配

**核心设计**：通过 `MiddlewareFeatures` dataclass 控制 21 个中间件位点的开关，确保无论从哪个入口创建 agent，中间件顺序都一致。

**解决的问题**：原有 `factory.py` 和 `make_lead_agent` 两条路径组装中间件时顺序不一致。

### 3.5 专精 Agent

| Agent | 定位 | 关键约束 |
|-------|------|----------|
| **Explore** | 只读代码探索 | 绝对不能写文件；只允许 Glob/Grep/FileRead/只读 Bash |
| **Plan** | 纯规划不执行 | 输出 step-by-step 计划 + Critical Files + Risks + Complexity |
| **Verification** | 对抗性验证 | 目标是 try to break it；必须执行 build/test/lint/adversarial probes；输出 VERDICT: PASS/FAIL/PARTIAL |

### 3.6 模块化 Prompt 装配

**核心设计**：`SystemPromptBuilder` 流式构建器，将 system prompt 拆分为**静态前缀**和**动态后缀**，中间用 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` 标记分隔。

**缓存优化**：静态前缀在多轮对话中不变，LLM API 的 prompt-caching 可直接复用。

```python
prompt = (
    SystemPromptBuilder(agent_name="DeerFlow 2.0")
    .with_memory(memory_text)
    .with_skills(skills_section)
    .with_environment(cwd="/workspace", date_str="2026-04-01")
    .with_specialized_agents(verification=True, explore=True, plan=True)
    .build()
)
```

### 3.7 上下文压缩引擎

**核心设计**：确定性本地压缩（不需要 LLM 调用），保留最近 N 条消息，中间段生成结构化摘要。

**摘要结构**：
- `[Previously]` — 已有摘要（再压缩时 merge）
- `[User requests]` — 用户请求摘要
- `[Tools used]` — 使用过的工具名集合
- `[Key paths]` — 提及的文件路径
- `[Timeline]` — 对话时间线

**续写契约**：压缩后注入 system message："请直接继续工作，不要重新自我介绍，不要复述已完成内容。"

**TokenBudget**：轻量级 token 估算器，4 字符 ≈ 1 token，支持 `should_compact(threshold=0.8)` 阈值判断。

### 3.8 插件系统

**核心设计**：通过 `plugin.json` manifest 声明工具、Hook 和权限需求。

**注册流程**：
1. `discover_plugins()` 扫描配置目录
2. 解析每个目录下的 `plugin.json` 为 `PluginManifest`
3. `PluginRegistry.register()` 验证工具名唯一性（插件间 + 内置冲突检测）
4. `aggregated_tools()` / `aggregated_hook_configs()` 聚合所有启用插件的贡献

---

## 四、配置指南

### 4.1 config.yaml 新增段落

#### 权限配置

```yaml
permissions:
  enabled: true          # 默认开启，allow 模式无行为变化
  mode: "allow"          # allow / prompt / workspace_write / read_only / danger_full_access
  tool_overrides:        # 按工具名覆盖权限要求
    bash: "danger_full_access"
    write_file: "workspace_write"
```

收紧示例 — 只允许读操作：
```yaml
permissions:
  enabled: true
  mode: "read_only"
```

#### Hook 配置

```yaml
hooks:
  enabled: true          # 默认开启，无条目时零开销
  pre_tool_use:
    - command: "python scripts/audit.py"                    # 外部进程 hook
    - command: "python scripts/check_paths.py"
      tools: ["bash", "write_file"]                         # 仅对指定工具生效
    - use: "mypackage.hooks:my_python_hook"                 # Python 函数 hook
  post_tool_use:
    - command: "python scripts/post_audit.py"
  post_tool_use_failure: []
```

#### 上下文压缩

```yaml
context:
  compaction:
    enabled: true
    max_estimated_tokens: 80000
    preserve_recent_messages: 6
```

#### 插件

```yaml
plugins:
  enabled: true
  directories:
    - "~/.deerflow/plugins"
    - ".deerflow/plugins"
```

### 4.2 编写自定义 Hook

**外部进程 Hook**（任何语言）：

```bash
#!/usr/bin/env bash
# scripts/audit_hook.sh
# stdin: JSON payload, env: HOOK_EVENT, HOOK_TOOL_NAME, HOOK_TOOL_INPUT

echo "[$(date)] $HOOK_EVENT: $HOOK_TOOL_NAME" >> /var/log/deerflow-audit.log

# exit 0 = allow, exit 2 = deny
if [ "$HOOK_TOOL_NAME" = "bash" ]; then
  echo "bash tool requires manual review"
  exit 2  # deny
fi
exit 0    # allow
```

**Python Hook**：

```python
# mypackage/hooks.py
from deerflow.hooks.types import HookPayload, HookResult

def my_audit_hook(payload: HookPayload) -> HookResult:
    print(f"[audit] {payload.event}: {payload.tool_name}")
    if "rm -rf" in str(payload.tool_input):
        return HookResult.denied("Dangerous command blocked")
    return HookResult.allowed()
```

配置引用：
```yaml
hooks:
  enabled: true
  pre_tool_use:
    - use: "mypackage.hooks:my_audit_hook"
```

### 4.3 编写插件

创建 `~/.deerflow/plugins/my-plugin/plugin.json`：

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "My custom plugin",
  "tools": [
    {
      "name": "custom_search",
      "command": "python search.py",
      "description": "Custom search tool",
      "required_permission": "read_only"
    }
  ],
  "hooks": {
    "pre_tool_use": ["hooks/check.sh"],
    "post_tool_use": []
  }
}
```

---

## 五、测试验证报告

### 5.1 单元测试（67/67 通过）

| 模块 | 测试数 | 关键覆盖点 |
|------|--------|-----------|
| 分层权限模型 | 9 | 层级排序、5 种 mode 行为、Prompter 交互、策略不可变性、未注册工具默认严格 |
| Hook 治理层 | 16 | 5 种事件类型、外部进程 exit 0/2/1 协议、环境变量传递、Python callable、Runner 顺序执行+deny 短路、工具过滤、from_config 加载 |
| 工具执行流水线 | 5 | 完整 5 阶段流程、权限拒绝、Hook 拒绝、异常处理、反馈合并 |
| 专精 Agent | 7 | 3 个 agent 配置完整性（name/system_prompt/disallowed_tools） |
| Prompt Builder | 6 | 模块化装配、缓存边界位置、Memory/Skills/Environment 注入、动态段在边界之后 |
| 上下文压缩 | 8 | TokenBudget 追踪、阈值判断、确定性摘要、路径提取、短对话保护、再压缩 merge |
| 插件系统 | 7 | Manifest 创建、Registry 注册、工具/Hook 聚合、插件间冲突检测、内置工具冲突检测 |
| 中间件构建器 | 3 | 功能标志控制、最小链/基础链构建、新字段存在性 |

### 5.2 集成测试（通过）

**测试场景**：在 `config.yaml` 中启用权限（`allow` + `tool_overrides`）和 Hook（外部审计脚本），验证：

1. `AppConfig.from_file()` 正确加载 permissions 和 hooks 段落
2. `build_pipeline_from_config()` 构建出正确的 Pipeline（mode=ALLOW, 2 个 tool_overrides, 2 个 hooks）
3. 执行 `web_search` 工具通过完整流水线，pre-hook 和 post-hook 均触发
4. Hook 反馈正确合并到工具输出中
5. 审计日志文件记录了正确的 event 和 tool_name

**审计日志输出**：
```
[23:17:49] EVENT=pre_tool_use TOOL=web_search
[23:17:49] EVENT=post_tool_use TOOL=web_search
```

### 5.3 运行时验证

DeerFlow 完整应用（LangGraph + Gateway + Frontend + Nginx）在启用所有新模块后正常启动，Claude Sonnet 4.6 模型正常响应，前端交互正常。

---

## 六、新增文件清单

### 新增 28 个文件

```
deerflow/permissions/__init__.py
deerflow/permissions/mode.py
deerflow/permissions/policy.py
deerflow/permissions/prompter.py
deerflow/permissions/middleware.py
deerflow/config/permissions_config.py

deerflow/hooks/__init__.py
deerflow/hooks/types.py
deerflow/hooks/runner.py
deerflow/hooks/external.py
deerflow/hooks/python_hook.py
deerflow/hooks/middleware.py
deerflow/config/hooks_config.py

deerflow/tools/execution.py

deerflow/agents/middleware_builder.py

deerflow/subagents/builtins/explore_agent.py
deerflow/subagents/builtins/plan_agent.py
deerflow/subagents/builtins/verification_agent.py

deerflow/prompts/__init__.py
deerflow/prompts/builder.py
deerflow/prompts/sections.py

deerflow/context/__init__.py
deerflow/context/compaction.py
deerflow/context/budget.py
deerflow/context/middleware.py

deerflow/plugins/__init__.py
deerflow/plugins/manifest.py
deerflow/plugins/registry.py
deerflow/plugins/loader.py
deerflow/plugins/tools.py
```

### 修改 3 个文件

```
deerflow/subagents/builtins/__init__.py  — 注册 explore/plan/verification agent
deerflow/config/app_config.py            — 加载 permissions + hooks 配置段
config.example.yaml                      — config_version 5 + 新段落文档及默认值
```

---

## 七、后续演进方向

| 方向 | 说明 |
|------|------|
| **权限 UI 集成** | 在前端实现 `PermissionPrompter` 的 WebSocket 版本，让用户在浏览器中实时审批高风险工具调用 |
| **内置审计 Hook** | 提供 `deerflow.hooks.builtins:audit_logger` 等开箱即用的 hook 实现 |
| **Prompt Builder 接管现有 prompt** | 将 `lead_agent/prompt.py` 中的单体 prompt 逐步迁移到 `SystemPromptBuilder` |
| **CompactionEngine 接管 Summarization** | 用确定性压缩替代或辅助 LLM-based summarization，降低 token 消耗 |
| **插件市场** | 实现 `marketplace.json` + 远程安装流程，让社区贡献插件 |
| **Verification Agent 自动触发** | 在关键操作（如文件写入、bash 执行）后自动调度 Verification Agent 做回归验证 |
| **Hook 异步支持** | `HookRunner` 增加 `arun()` 异步方法，适配高并发场景 |
