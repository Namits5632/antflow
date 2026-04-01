"""SystemPromptBuilder — modular prompt assembly with cache boundary.

Usage::

    prompt = (
        SystemPromptBuilder(agent_name="DeerFlow 2.0")
        .with_memory(memory_text)
        .with_skills(skills_section)
        .with_subagent(subagent_section)
        .build()
    )

The resulting string has a clear static/dynamic boundary so that LLM API
prompt-caching can reuse the static prefix across turns.
"""

from __future__ import annotations

from deerflow.prompts.sections import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    actions_section,
    code_citing_section,
    environment_section,
    git_safety_section,
    intro_section,
    linter_section,
    making_code_changes_section,
    output_efficiency_section,
    session_guidance_section,
    system_rules_section,
    task_philosophy_section,
    tone_style_section,
    tool_usage_section,
)


class SystemPromptBuilder:
    """Builder for modular system prompt assembly."""

    def __init__(self, agent_name: str = "DeerFlow 2.0"):
        self._agent_name = agent_name
        self._soul: str | None = None
        self._memory: str | None = None
        self._skills_section: str | None = None
        self._deferred_tools_section: str | None = None
        self._subagent_section: str | None = None
        self._mcp_instructions: str | None = None
        self._project_rules: str | None = None
        self._clarification_section: str | None = None
        self._working_directory_section: str | None = None
        self._citations_section: str | None = None
        self._extra_static: list[str] = []
        self._extra_dynamic: list[str] = []

        self._cwd: str | None = None
        self._date_str: str | None = None
        self._subagent_enabled: bool = False
        self._has_verification: bool = False
        self._has_explore: bool = False
        self._has_plan: bool = False

    # ---- Fluent setters ----

    def with_soul(self, soul: str) -> SystemPromptBuilder:
        self._soul = soul
        return self

    def with_memory(self, memory: str) -> SystemPromptBuilder:
        self._memory = memory
        return self

    def with_skills(self, section: str) -> SystemPromptBuilder:
        self._skills_section = section
        return self

    def with_deferred_tools(self, section: str) -> SystemPromptBuilder:
        self._deferred_tools_section = section
        return self

    def with_subagent(self, section: str, *, enabled: bool = True) -> SystemPromptBuilder:
        self._subagent_section = section
        self._subagent_enabled = enabled
        return self

    def with_mcp_instructions(self, instructions: str) -> SystemPromptBuilder:
        self._mcp_instructions = instructions
        return self

    def with_project_rules(self, rules: str) -> SystemPromptBuilder:
        self._project_rules = rules
        return self

    def with_clarification(self, section: str) -> SystemPromptBuilder:
        self._clarification_section = section
        return self

    def with_working_directory(self, section: str) -> SystemPromptBuilder:
        self._working_directory_section = section
        return self

    def with_citations(self, section: str) -> SystemPromptBuilder:
        self._citations_section = section
        return self

    def with_environment(self, cwd: str | None = None, date_str: str | None = None) -> SystemPromptBuilder:
        self._cwd = cwd
        self._date_str = date_str
        return self

    def with_specialized_agents(
        self,
        *,
        verification: bool = False,
        explore: bool = False,
        plan: bool = False,
    ) -> SystemPromptBuilder:
        self._has_verification = verification
        self._has_explore = explore
        self._has_plan = plan
        return self

    def add_static_section(self, section: str) -> SystemPromptBuilder:
        self._extra_static.append(section)
        return self

    def add_dynamic_section(self, section: str) -> SystemPromptBuilder:
        self._extra_dynamic.append(section)
        return self

    # ---- Build ----

    def build(self) -> str:
        """Assemble the full system prompt with static/dynamic boundary."""
        sections: list[str] = []

        # ===== Static prefix (cacheable) =====
        sections.append(intro_section(self._agent_name))
        sections.append(system_rules_section())
        sections.append(task_philosophy_section())
        sections.append(actions_section())
        sections.append(git_safety_section())
        sections.append(tool_usage_section())
        sections.append(making_code_changes_section())
        sections.append(linter_section())
        sections.append(tone_style_section())
        sections.append(output_efficiency_section())
        sections.append(code_citing_section())
        for extra in self._extra_static:
            sections.append(extra)

        # ===== Cache boundary =====
        sections.append(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)

        # ===== Dynamic suffix (per-session) =====
        if self._soul:
            sections.append(self._soul)

        if self._memory:
            sections.append(self._memory)

        sections.append(environment_section(self._cwd, self._date_str))

        guidance = session_guidance_section(
            subagent_enabled=self._subagent_enabled,
            has_verification=self._has_verification,
            has_explore=self._has_explore,
            has_plan=self._has_plan,
        )
        if guidance:
            sections.append(guidance)

        if self._skills_section:
            sections.append(self._skills_section)

        if self._deferred_tools_section:
            sections.append(self._deferred_tools_section)

        if self._subagent_section:
            sections.append(self._subagent_section)

        if self._clarification_section:
            sections.append(self._clarification_section)

        if self._working_directory_section:
            sections.append(self._working_directory_section)

        if self._citations_section:
            sections.append(self._citations_section)

        if self._mcp_instructions:
            sections.append(self._mcp_instructions)

        if self._project_rules:
            sections.append(self._project_rules)

        for extra in self._extra_dynamic:
            sections.append(extra)

        return "\n\n".join(s for s in sections if s and s.strip())
