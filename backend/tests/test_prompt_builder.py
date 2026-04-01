"""Tests for the modular prompt builder (deerflow.prompts)."""

from deerflow.prompts import SystemPromptBuilder, split_prompt_for_caching
from deerflow.prompts.sections import SYSTEM_PROMPT_DYNAMIC_BOUNDARY


class TestSystemPromptBuilder:
    def test_basic_build(self):
        prompt = SystemPromptBuilder(agent_name="TestAgent").build()
        assert len(prompt) > 100
        assert "TestAgent" in prompt

    def test_contains_boundary(self):
        prompt = SystemPromptBuilder().build()
        assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in prompt

    def test_static_sections_before_boundary(self):
        prompt = SystemPromptBuilder().build()
        idx = prompt.index(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
        static = prompt[:idx]
        assert "<role>" in static
        assert "<system_rules>" in static
        assert "<task_philosophy>" in static
        assert "<git_safety>" in static
        assert "<linter_feedback>" in static

    def test_dynamic_sections_after_boundary(self):
        prompt = SystemPromptBuilder().with_memory("[Memory] user prefers Chinese").with_skills("[Skills] web_search").build()
        idx = prompt.index(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
        dynamic = prompt[idx:]
        assert "[Memory]" in dynamic
        assert "[Skills]" in dynamic

    def test_environment_injection(self):
        prompt = SystemPromptBuilder().with_environment(cwd="/workspace", date_str="2026-04-01").build()
        assert "/workspace" in prompt
        assert "2026-04-01" in prompt

    def test_specialized_agents(self):
        prompt = SystemPromptBuilder().with_subagent("subagent section", enabled=True).with_specialized_agents(verification=True, explore=True, plan=True).build()
        assert "verification" in prompt
        assert "explore" in prompt

    def test_fluent_interface_returns_self(self):
        builder = SystemPromptBuilder()
        assert builder.with_memory("x") is builder
        assert builder.with_skills("y") is builder
        assert builder.with_environment() is builder

    def test_extra_sections(self):
        prompt = SystemPromptBuilder().add_static_section("<custom_static>test</custom_static>").add_dynamic_section("<custom_dynamic>test</custom_dynamic>").build()
        idx = prompt.index(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
        assert "<custom_static>" in prompt[:idx]
        assert "<custom_dynamic>" in prompt[idx:]


class TestSplitPromptForCaching:
    def test_split_at_boundary(self):
        prompt = SystemPromptBuilder().with_memory("test memory").build()
        static, dynamic = split_prompt_for_caching(prompt)
        assert len(static) > 0
        assert len(dynamic) > 0
        assert "test memory" in dynamic
        assert "<role>" in static

    def test_no_boundary(self):
        static, dynamic = split_prompt_for_caching("simple prompt without boundary")
        assert static == "simple prompt without boundary"
        assert dynamic == ""
