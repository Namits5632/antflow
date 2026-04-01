# DeerFlow 深度改造设计文档 —— 引入 Claude Code 先进架构

## 一、改造背景

本次改造基于对 Claude Code 泄露源码（claw-code 项目）和《Claude Code 源码深度研究报告》的系统分析，将 Claude Code 中被验证有效的 Agent Operating System 级设计引入 DeerFlow。

Claude Code 的真正优势不是一段 system prompt，而是一整套把 prompt architecture、tool runtime governance、permission model、agent orchestration、skill packaging、plugin system、hooks governance、MCP integration、context hygiene 和 product engineering 全部统一起来的系统。

## 二、改造模块清单

### 2.1 分层权限模型 (`deerflow/permissions/`)

**新增文件:**
- `permissions/__init__.py` — 包导出
- `permissions/mode.py` — `PermissionMode` 枚举（READ_ONLY < WORKSPACE_WRITE < DANGER_FULL_ACCESS < PROMPT < ALLOW）
- `permissions/policy.py` — `PermissionPolicy` 策略引擎，每个工具声明所需权限级别
- `permissions/prompter.py` — `PermissionPrompter` 抽象 + `AutoAllowPrompter` / `AutoDenyPrompter`
- `permissions/middleware.py` — `PermissionMiddleware`，插入中间件链中在 GuardrailMiddleware 之前

**配置:** `config/permissions_config.py` — mode + tool_overrides

**设计原则:**
- 未注册工具默认要求 `DANGER_FULL_ACCESS`（最严），防止漏登记工具被低权限放行
- `ALLOW` 模式（默认）完全兼容旧行为
- `PermissionPrompter` 为 trait 抽象，支持 CLI / HTTP / WebSocket 等不同审批通道

### 2.2 Hook 治理层 (`deerflow/hooks/`)

**新增文件:**
- `hooks/__init__.py` — 包导出
- `hooks/types.py` — `HookEvent`, `HookResult`, `HookConfig`, `HookPayload`
- `hooks/runner.py` — `HookRunner`，顺序执行 hook 列表，deny 短路
- `hooks/external.py` — 外部进程 hook 执行器（兼容 Claude Code 协议：exit 0=allow, 2=deny）
- `hooks/python_hook.py` — Python 函数 hook 执行器
- `hooks/middleware.py` — `HookMiddleware`

**配置:** `config/hooks_config.py` — enabled + pre_tool_use / post_tool_use / post_tool_use_failure

**设计原则:**
- Hook 可修改工具输入（`updated_input`）、拒绝执行、注入反馈
- Hook 的 permission_behavior 不能绕开核心权限模型
- 外部进程协议与 Claude Code 一致（stdin JSON + env vars + exit code 语义）

### 2.3 工具执行流水线 (`deerflow/tools/execution.py`)

**新增文件:** `tools/execution.py` — `ToolExecutionPipeline`

**执行阶段:**
1. 权限检查 → 2. PreToolUse hooks → 3. 实际执行 → 4. PostToolUse hooks → 5. 合并 hook 反馈

**设计原则:**
- 将工具执行从"直接调用"升级为多阶段流水线
- 每个阶段的 deny 都产生结构化的 error ToolMessage，模型可感知
- `build_pipeline_from_config()` 便捷函数从当前配置构建完整流水线

### 2.4 统一中间件装配 (`deerflow/agents/middleware_builder.py`)

**新增文件:** `agents/middleware_builder.py` — `CanonicalMiddlewareBuilder`

**标准顺序（21 个位点）:**
```
[0]  ThreadDataMiddleware
[1]  UploadsMiddleware
[2]  SandboxMiddleware
[3]  DanglingToolCallMiddleware
[4]  PermissionMiddleware        ← NEW
[5]  GuardrailMiddleware
[6]  HookMiddleware              ← NEW
[7]  SandboxAuditMiddleware
[8]  ToolErrorHandlingMiddleware
[9]  SummarizationMiddleware
[10] CompactionMiddleware        ← NEW
[11] TodoMiddleware
[12] TokenUsageMiddleware
[13] TitleMiddleware
[14] MemoryMiddleware
[15] ViewImageMiddleware
[16] DeferredToolFilterMiddleware
[17] SubagentLimitMiddleware
[18] LoopDetectionMiddleware
[19] [custom middlewares]
[20] ClarificationMiddleware     ← always last
```

### 2.5 专业化内建 Agent (`deerflow/subagents/builtins/`)

**新增文件:**
- `explore_agent.py` — 只读代码探索专家
- `plan_agent.py` — 纯规划 Agent
- `verification_agent.py` — 对抗性验证 Agent

**Explore Agent:**
- 绝对只读，不能创建/修改/删除文件
- 只允许 Glob、Grep、FileRead、只读 Bash
- 快速探索代码库，返回结构化发现

**Plan Agent:**
- 只读，输出 step-by-step 实施计划
- 必须列出 Critical Files for Implementation
- 包含 Approach Analysis、Risks、Estimated Complexity

**Verification Agent:**
- 目标是 **try to break it**，不是确认没问题
- 防止两类失败：verification avoidance 和 80% blindness
- 必须执行 build、test suite、linter、adversarial probes
- 每个检查带 command + output observed
- 输出 VERDICT: PASS / FAIL / PARTIAL

### 2.6 模块化 Prompt 装配 (`deerflow/prompts/`)

**新增文件:**
- `prompts/__init__.py`
- `prompts/builder.py` — `SystemPromptBuilder` 流式构建器
- `prompts/sections.py` — 各独立 section 函数 + `SYSTEM_PROMPT_DYNAMIC_BOUNDARY`

**静态前缀（可缓存）:**
- intro_section — 身份与基础定位
- system_rules_section — 运行时规则
- task_philosophy_section — 做任务哲学（不过度抽象/重构/加功能）
- actions_section — 风险动作规范
- tool_usage_section — 工具使用规范
- tone_style_section — 交互风格
- output_efficiency_section — 输出效率

**缓存边界:** `SYSTEM_PROMPT_DYNAMIC_BOUNDARY`

**动态后缀（按会话变化）:**
- soul, memory, environment, session_guidance, skills, deferred_tools, subagent, mcp_instructions, project_rules

### 2.7 上下文压缩引擎 (`deerflow/context/`)

**新增文件:**
- `context/__init__.py`
- `context/compaction.py` — `CompactionEngine` 确定性压缩
- `context/budget.py` — `TokenBudget` 预算跟踪
- `context/middleware.py` — `CompactionMiddleware`

**压缩策略:**
- 保留尾部 N 条消息原样
- 中间段生成结构化摘要（用户请求、工具名、关键路径、时间线）
- 处理再压缩（merge existing summary，不覆盖）
- 续写契约消息（"请直接继续工作，不要重复寒暄"）
- 确定性本地执行，不需要 LLM 调用

### 2.8 插件系统 (`deerflow/plugins/`)

**新增文件:**
- `plugins/__init__.py`
- `plugins/manifest.py` — `PluginManifest` 模型（plugin.json schema）
- `plugins/registry.py` — `PluginRegistry`（工具唯一性检查、hook 聚合）
- `plugins/loader.py` — 目录扫描与加载
- `plugins/tools.py` — `PluginTool` 适配器（外部进程执行）

**Manifest 格式:**
```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "tools": [{ "name": "...", "command": "...", "required_permission": "..." }],
  "hooks": { "pre_tool_use": ["scripts/check.py"] },
  "permissions": { "read": true, "write": false }
}
```

## 三、配置兼容性

- `config_version` 从 4 升级到 5
- 所有新功能段落默认关闭或使用最宽松模式
- `permissions.mode = "allow"` 时完全兼容旧行为
- `hooks.enabled = false` 时不加载任何 hook
- 新的 `AppConfig.from_file` 加载逻辑在现有段落之后处理新段落

## 四、文件清单

### 新增文件（25 个）
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

### 修改文件（3 个）
```
deerflow/subagents/builtins/__init__.py  — 注册 explore/plan/verification
deerflow/config/app_config.py            — 加载 permissions + hooks config
config.example.yaml                      — config_version 5 + 新段落文档
```
