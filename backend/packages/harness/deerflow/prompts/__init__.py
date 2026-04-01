"""Modular system prompt assembly architecture.

Instead of a single monolithic template, prompts are composed from
independent sections with a clear static/dynamic boundary for cache
optimization.
"""

from deerflow.prompts.builder import SystemPromptBuilder
from deerflow.prompts.sections import SYSTEM_PROMPT_DYNAMIC_BOUNDARY


def split_prompt_for_caching(prompt: str) -> tuple[str, str]:
    """Split a prompt at the cache boundary into (static_prefix, dynamic_suffix).

    The static prefix can be cached across turns by LLM APIs that support
    prompt caching (e.g. Anthropic's ``cache_control`` or OpenAI's automatic
    prompt caching).

    If the boundary marker is not found, the entire prompt is treated as static.
    """
    if SYSTEM_PROMPT_DYNAMIC_BOUNDARY in prompt:
        idx = prompt.index(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
        return prompt[:idx], prompt[idx + len(SYSTEM_PROMPT_DYNAMIC_BOUNDARY) :]
    return prompt, ""


__all__ = ["SystemPromptBuilder", "split_prompt_for_caching"]
