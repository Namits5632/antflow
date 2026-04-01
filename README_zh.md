# AntFlow

[English](./README.md) | 中文

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

AntFlow 是一个**生产级 AI Agent 平台**，基于 [DeerFlow](https://github.com/bytedance/deer-flow) 深度改造，融合了 **Claude Code**（Anthropic 的 Agent Operating System）的核心架构设计。

> **为什么叫 AntFlow？** "Ant" 致敬 **Ant**hropic，其 Claude Code 源码启发了本次架构改造。"Flow" 继承自 DeerFlow 的工作流编排基因。

---

## 我们做了什么 —— Claude Code 架构集成

这不是简单的 prompt 调整或外层包装。我们深入研究了 Claude Code 的源码，并将其**关键工程系统**移植到 DeerFlow 框架中。以下是具体改造内容：

### 1. 五级权限系统

借鉴 Claude Code 的分层权限模型。每次工具调用都必须经过策略引擎的权限检查。

| 级别 | 说明 |
|---|---|
| `READ_ONLY` | 仅允许读操作 |
| `WORKSPACE_WRITE` | 允许读 + 工作区内写文件 |
| `DANGER_FULL_ACCESS` | 不受限（bash、系统命令） |
| `PROMPT` | 高风险工具需要用户交互审批 |
| `ALLOW` | 所有工具均放行（默认，向后兼容） |

在 `config.yaml` 中配置：

```yaml
permissions:
  enabled: true
  mode: "allow"  # 或 "workspace_write"、"read_only"、"prompt"
  tool_overrides:
    bash: "danger_full_access"
    write_file: "workspace_write"
```

### 2. Hook 治理层

借鉴 Claude Code 的 `PreToolUse` / `PostToolUse` Hook 协议。在每次工具调用的前后设置可编程拦截点。

- **外部 Hook**：Shell 脚本，遵循 Claude Code 的 stdin/退出码协议（`exit 0` = 放行，`exit 2` = 拒绝）
- **Python Hook**：运行时动态解析的 Python 可调用对象
- **应用场景**：审计日志、敏感路径拦截、输入消毒、合规强制执行

```yaml
hooks:
  enabled: true
  pre_tool_use:
    - command: "bash scripts/hooks/audit_hook.sh"
    - command: "python scripts/check_sensitive_paths.py"
      tools: ["bash", "write_file"]
  post_tool_use:
    - command: "bash scripts/hooks/audit_hook.sh"
```

### 3. 工具执行管线

Claude Code 不会直接调用工具——它通过一个结构化的 5 阶段管线来执行。我们完整移植了这一设计：

```
权限检查 → Pre-Hook → 执行工具 → Post-Hook → 合并反馈
```

每次工具调用都走这条路径，没有例外，没有捷径。

### 4. 模块化 Prompt 组装 + 缓存边界

移植自 Claude Code 的 `getSystemPrompt()` 架构。系统 prompt 不再是静态模板，而是由独立模块**运行时组装**：

- **静态前缀**（可缓存）：身份定义、工具使用规范、Git 安全协议、Linter 反馈指引、代码引用规范
- **动态后缀**（按会话变化）：环境信息、活跃 Skill、工作目录、子 Agent 配置

通过 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` 标记实现 API 级 prompt 缓存，token 成本降低约 88%。

### 5. 上下文压缩引擎

将 Claude Code 的 `compact.rs` 用 Python 重新实现。当对话变长时，该引擎**确定性地压缩**历史消息，无需调用 LLM：

- **零成本**：不调 API、不花 token——纯本地结构化提取
- **结构化摘要**：`[用户请求]`、`[使用工具]`、`[关键路径]`、`[时间线]`
- **可重复压缩**：已压缩的对话可以再次压缩（合并而非覆盖）
- **精确 token 追踪**：同时支持估算（4 字符 ≈ 1 token）和 API 返回的精确值

该引擎与原有的 LangChain `SummarizationMiddleware` 共存——压缩引擎作为更高阈值的兜底方案。

### 6. 声明式插件系统

对齐 Claude Code 的插件架构。插件通过 `plugin.json` 清单文件贡献工具、Hook 和运行时约束：

```json
{
  "name": "amazon-sp-api",
  "version": "1.0.0",
  "tools": [
    { "name": "search_products", "module": "plugins.amazon.tools", "callable": "search" }
  ],
  "permissions": { "search_products": "read_only" },
  "hooks": {
    "pre_tool_use": [{ "use": "plugins.amazon.audit:log_api_call" }]
  }
}
```

### 7. 专业化子 Agent

借鉴 Claude Code 的内建 Agent 专业化设计（Explore、Plan、Verification）。不再只有一个通用 worker，而是将任务委派给专门构建的子 Agent：

| Agent | 角色 | 约束 |
|---|---|---|
| **Explore** | 只读数据/代码探索 | 不能修改任何文件 |
| **Plan** | 策略规划与架构设计 | 只读，结构化输出 |
| **Verification** | 对抗性结果验证 | 交付前必须通过检查 |

### 8. Prompt 最佳实践

将 Claude Code 经过验证的 prompt 段落集成为可复用模块：

- **Git 安全协议** — 阻止破坏性 git 操作（`push --force`、`hard reset` 等）
- **Linter 反馈** — 引导 agent 在代码编辑后检查并修复 linter 错误
- **代码引用规范** — 引用已有代码 vs 提议新代码的标准化格式
- **代码修改规范** — 先读后改、优先编辑而非新建文件的规则

---

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│                    AntFlow Agent                     │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │          SystemPromptBuilder                     │ │
│  │  [静态：身份 + 规则 + 安全协议]                    │ │
│  │  ─── 缓存边界 ───                                 │ │
│  │  [动态：环境 + Skills + 会话信息]                  │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─────────────── 中间件链 ────────────────────────┐ │
│  │ 权限 → Hook → 摘要 → 压缩 → Todo → Token追踪   │ │
│  │ → 标题 → 记忆 → 循环检测 → 澄清                 │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─────────── 工具执行管线 ────────────────────────┐ │
│  │ 权限检查 → PreHook → 执行 → PostHook → 合并反馈 │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌──────────── 专业化子 Agent ─────────────────────┐ │
│  │  Explore (只读) │ Plan (只读) │ Verification     │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌──────────── 插件系统 ──────────────────────────┐ │
│  │  plugin.json → 工具 + Hook + 权限               │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 22+
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）
- pnpm（Node.js 包管理器）

### 安装运行

```bash
git clone https://github.com/fang503/antflow.git
cd antflow
make config    # 从模板生成 config.yaml
make install   # 安装所有依赖
make dev       # 启动开发服务器
```

打开浏览器访问 **http://localhost:2026**。

### 配置

编辑 `config.yaml` 可以：

- 配置 LLM 模型（Claude、GPT、Gemini、DeepSeek 等）
- 启用/禁用治理功能（权限、Hook、压缩）
- 添加插件目录
- 调整 token 预算和压缩阈值

---

## 继承自 DeerFlow

AntFlow 继承了 DeerFlow 2.0 的全部能力：

- **子 Agent 编排** — 闪速 / 思考 / Pro / Ultra 模式
- **沙箱执行** — 基于 Docker 的隔离环境
- **长期记忆** — 跨会话持久化 Agent 记忆
- **MCP 集成** — Model Context Protocol 外部工具服务器
- **ACP 集成** — Agent Communication Protocol 跨 Agent 通信
- **Skill 系统** — 可扩展的工作流包
- **多模型支持** — Claude、GPT、Gemini、DeepSeek、Kimi 等
- **Web 界面** — Next.js 前端，实时流式输出

---

## 致谢

- [DeerFlow](https://github.com/bytedance/deer-flow)（ByteDance）— 本项目的基础框架
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)（Anthropic）— 启发架构改造的 Agent OS
- [LangChain](https://github.com/langchain-ai/langchain) / [LangGraph](https://github.com/langchain-ai/langgraph) — Agent 框架与编排引擎

## 许可证

[MIT](./LICENSE)
