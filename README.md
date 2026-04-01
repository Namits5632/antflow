# AntFlow

[English](./README.md) | [中文](./README_zh.md)

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

AntFlow is a **production-grade AI agent platform** forked from [DeerFlow](https://github.com/bytedance/deer-flow) and deeply enhanced with core architectural patterns from **Claude Code** — Anthropic's Agent Operating System.

> **Why the name?** "Ant" nods to **Ant**hropic, whose Claude Code source code inspired the architectural overhaul. "Flow" inherits from DeerFlow's workflow orchestration DNA.

---

## What We Changed — Claude Code Architecture Integration

This is not a thin wrapper or prompt tweak. We studied Claude Code's source code in depth and **ported its key engineering systems** into the DeerFlow harness. Here is what was added:

### 1. Five-Level Permission System

Borrowed from Claude Code's layered permission model. Every tool call now passes through a policy engine before execution.

| Level | Description |
|---|---|
| `READ_ONLY` | Only read operations allowed |
| `WORKSPACE_WRITE` | Read + file write within workspace |
| `DANGER_FULL_ACCESS` | Unrestricted (bash, system commands) |
| `PROMPT` | High-risk tools require interactive user approval |
| `ALLOW` | All tools permitted (default, backward-compatible) |

Configure in `config.yaml`:

```yaml
permissions:
  enabled: true
  mode: "allow"  # or "workspace_write", "read_only", "prompt"
  tool_overrides:
    bash: "danger_full_access"
    write_file: "workspace_write"
```

### 2. Hook Governance Layer

Inspired by Claude Code's `PreToolUse` / `PostToolUse` hook protocol. Programmable interception points before and after every tool call.

- **External hooks**: Shell scripts following Claude Code's stdin/exit-code protocol (`exit 0` = allow, `exit 2` = deny)
- **Python hooks**: Callable functions resolved at runtime
- **Use cases**: Audit logging, sensitive path blocking, input sanitization, compliance enforcement

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

### 3. Tool Execution Pipeline

Claude Code doesn't call tools directly — it runs them through a structured 5-stage pipeline. We ported this:

```
Permission Check → Pre-Hook → Execute Tool → Post-Hook → Merge Feedback
```

Every tool call follows this path. No exceptions, no shortcuts.

### 4. Modular Prompt Assembly with Cache Boundary

Ported from Claude Code's `getSystemPrompt()` architecture. The system prompt is no longer a static template — it's a **runtime-assembled** composition of independent sections:

- **Static prefix** (cacheable): Identity, tool usage rules, git safety protocol, linter feedback guidelines, code citing rules
- **Dynamic suffix** (per-session): Environment info, active skills, working directory, subagent config

A `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` marker enables API-level prompt caching, reducing token costs by ~88%.

### 5. Context Compaction Engine

Claude Code's `compact.rs` reimplemented in Python. When conversations grow long, this engine **deterministically compresses** history without calling an LLM:

- **Zero cost**: No API calls, no token spend — pure local extraction
- **Structured summaries**: `[User requests]`, `[Tools used]`, `[Key paths]`, `[Timeline]`
- **Re-compaction**: Already-compacted conversations can be compacted again (merge, not overwrite)
- **Precise token tracking**: Supports both estimation (4 chars ≈ 1 token) and API-reported exact counts

This coexists with the original LangChain `SummarizationMiddleware` — compaction serves as a higher-threshold fallback.

### 6. Declarative Plugin System

Mirrors Claude Code's plugin architecture. Plugins contribute tools, hooks, and runtime constraints via `plugin.json` manifests:

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

### 7. Specialized Sub-Agents

Borrowed from Claude Code's built-in agent specialization (Explore, Plan, Verification). Instead of one generic worker, tasks are delegated to purpose-built sub-agents:

| Agent | Role | Constraints |
|---|---|---|
| **Explore** | Read-only code/data exploration | Cannot modify any files |
| **Plan** | Strategic planning and architecture | Read-only, structured output |
| **Verification** | Adversarial validation of results | Mandatory checks before delivery |

### 8. Prompt Best Practices

Integrated Claude Code's proven prompt sections as reusable modules:

- **Git Safety Protocol** — Prevents destructive git operations (`push --force`, `hard reset`, etc.)
- **Linter Feedback** — Guides the agent to check and fix linter errors after code edits
- **Code Citing** — Standardized format for referencing existing code vs. proposing new code
- **Making Code Changes** — Rules for reading before editing, preferring edits over new files

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    AntFlow Agent                     │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │          SystemPromptBuilder                     │ │
│  │  [Static: Identity + Rules + Safety]             │ │
│  │  ─── CACHE BOUNDARY ───                          │ │
│  │  [Dynamic: Env + Skills + Session]               │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─────────────── Middleware Chain ────────────────┐ │
│  │ Permission → Hook → Summarization → Compaction  │ │
│  │ → Todo → TokenUsage → Title → Memory → Loop     │ │
│  │ → Clarification                                  │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─────────── Tool Execution Pipeline ────────────┐ │
│  │ PermCheck → PreHook → Execute → PostHook → Merge│ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌──────────── Specialized SubAgents ─────────────┐ │
│  │  Explore (RO) │ Plan (RO) │ Verification (RO)  │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌──────────── Plugin System ─────────────────────┐ │
│  │  plugin.json → Tools + Hooks + Permissions      │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 22+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- pnpm (Node.js package manager)

### Setup

```bash
git clone https://github.com/fang503/antflow.git
cd antflow
make config    # Generate config.yaml from template
make install   # Install all dependencies
make dev       # Start development server
```

Open **http://localhost:2026** in your browser.

### Configuration

Edit `config.yaml` to:

- Configure your LLM model (Claude, GPT, Gemini, DeepSeek, etc.)
- Enable/disable governance features (permissions, hooks, compaction)
- Add plugin directories
- Adjust token budgets and compaction thresholds

---

## Inherited from DeerFlow

AntFlow inherits all of DeerFlow 2.0's capabilities:

- **Sub-Agent Orchestration** — Flash / Thinking / Pro / Ultra modes
- **Sandbox Execution** — Docker-based isolated environments
- **Long-Term Memory** — Persistent agent memory across sessions
- **MCP Integration** — Model Context Protocol for external tool servers
- **ACP Integration** — Agent Communication Protocol for agent-to-agent calls
- **Skill System** — Extensible workflow packages
- **Multi-Model Support** — Claude, GPT, Gemini, DeepSeek, Kimi, and more
- **Web UI** — Next.js frontend with real-time streaming

---

## Acknowledgments

- [DeerFlow](https://github.com/bytedance/deer-flow) by ByteDance — The foundation this project is built upon
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) by Anthropic — The Agent OS architecture that inspired the renovation
- [LangChain](https://github.com/langchain-ai/langchain) / [LangGraph](https://github.com/langchain-ai/langgraph) — Agent framework and orchestration

## License

[MIT](./LICENSE)
