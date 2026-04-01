"""Tests for the context compaction engine (deerflow.context)."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.context.budget import TokenBudget
from deerflow.context.compaction import CompactionConfig, CompactionEngine


class TestTokenBudget:
    def test_initial_state(self):
        b = TokenBudget(max_tokens=1000)
        assert b.current == 0
        assert b.remaining == 1000
        assert not b.should_compact()

    def test_add_text(self):
        b = TokenBudget(max_tokens=1000)
        b.add_text("Hello world!")
        assert b.current > 0
        assert b.remaining < 1000

    def test_should_compact_threshold(self):
        b = TokenBudget(max_tokens=1000)
        assert not b.should_compact(threshold=0.8)
        b.set_estimate(900)
        assert b.should_compact(threshold=0.8)

    def test_utilisation(self):
        b = TokenBudget(max_tokens=100)
        b.set_estimate(50)
        assert b.utilisation == pytest.approx(0.5)

    def test_reset(self):
        b = TokenBudget(max_tokens=100)
        b.set_estimate(50)
        b.reset()
        assert b.current == 0
        assert not b.is_precise

    def test_api_response_update(self):
        b = TokenBudget(max_tokens=100_000)
        b.update_from_api_response(prompt_tokens=5000, completion_tokens=1000, total_tokens=6000)
        assert b.is_precise
        assert b.current == 6000

    def test_api_response_with_cache_info(self):
        b = TokenBudget(max_tokens=100_000)
        b.update_from_api_response(total_tokens=5000, cache_read_tokens=3000, cache_creation_tokens=2000)
        assert b.current == 5000
        assert len(b._history) == 2


class TestCompactionEngine:
    @pytest.fixture
    def engine(self):
        return CompactionEngine(
            CompactionConfig(
                max_estimated_tokens=20,
                preserve_recent_messages=2,
            )
        )

    @pytest.fixture
    def long_conversation(self):
        return [
            HumanMessage(content="Please analyze /src/main.py"),
            AIMessage(content="I'll read that file for you."),
            HumanMessage(content="Also look at /src/utils.py"),
            AIMessage(content="Done. The file has utility functions."),
            HumanMessage(content="Now write tests"),
            AIMessage(content="Writing tests now."),
            HumanMessage(content="Show me the results"),
            AIMessage(content="All tests passed."),
        ]

    def test_should_compact_long_conversation(self, engine, long_conversation):
        assert engine.should_compact(long_conversation)

    def test_preserves_recent_messages(self, engine, long_conversation):
        result = engine.compact(long_conversation)
        assert result.preserved_count == 2

    def test_produces_summary(self, engine, long_conversation):
        result = engine.compact(long_conversation)
        assert len(result.summary_text) > 0

    def test_summary_mentions_paths(self, engine, long_conversation):
        result = engine.compact(long_conversation)
        assert "/src/main.py" in result.summary_text or "Key paths" in result.summary_text

    def test_short_conversation_preserved(self, engine):
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        result = engine.compact(msgs)
        assert result.preserved_count == 2
        assert result.removed_count == 0

    def test_empty_conversation(self, engine):
        result = engine.compact([])
        assert result.original_count == 0
        assert result.compacted_messages == []

    def test_compacted_messages_start_with_system(self, engine, long_conversation):
        result = engine.compact(long_conversation)
        assert isinstance(result.compacted_messages[0], SystemMessage)
        assert "compacted_summary" in str(result.compacted_messages[0].content)

    def test_re_compaction_merges(self, engine, long_conversation):
        result1 = engine.compact(long_conversation)
        extended = result1.compacted_messages + [
            HumanMessage(content="Add more features"),
            AIMessage(content="Adding features now."),
            HumanMessage(content="Done?"),
            AIMessage(content="Yes, all done."),
            HumanMessage(content="Review everything"),
            AIMessage(content="Reviewing."),
        ]
        engine2 = CompactionEngine(CompactionConfig(max_estimated_tokens=10, preserve_recent_messages=2))
        result2 = engine2.compact(extended)
        assert "Previously" in result2.summary_text
