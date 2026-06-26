"""
Tests for MessageReducer using LangChain BaseMessage objects.

These tests verify that the reducer works with real LangChain message types
without the package importing langchain_core itself.

Requires: pip install langchain-core
"""

import pytest

try:
    from langchain_core.messages import (
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )
    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False

from agentstate_reducer import MessageReducer, ReducerConfig


pytestmark = pytest.mark.skipif(
    not HAS_LANGCHAIN, reason="langchain-core not installed"
)


# ── Basic Behavior with LangChain Types ─────────────────────

class TestLangChainBasic:

    def test_no_pruning_under_threshold(self):
        reducer = MessageReducer(min_messages=5, max_messages=10)
        messages = [HumanMessage(content=f"msg-{i}") for i in range(8)]
        result = reducer.reduce(existing=messages)
        assert len(result.surviving) == 8
        assert len(result.pruned) == 0

    def test_concatenation(self):
        reducer = MessageReducer(min_messages=5, max_messages=20)
        existing = [HumanMessage(content="old")]
        new = [AIMessage(content="new")]
        result = reducer.reduce(existing=existing, new=new)
        assert len(result.surviving) == 2
        assert result.surviving[0].content == "old"
        assert result.surviving[1].content == "new"

    def test_preserves_system_message(self):
        reducer = MessageReducer(min_messages=3, max_messages=5)
        messages = [
            SystemMessage(content="You are helpful"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
            HumanMessage(content="q3"),
            AIMessage(content="a3"),
        ]
        result = reducer.reduce(existing=messages)
        assert isinstance(result.surviving[0], SystemMessage)
        assert result.surviving[0].content == "You are helpful"


# ── Pruning with LangChain Types ────────────────────────────

class TestLangChainPruning:

    def test_prunes_when_over_threshold(self):
        reducer = MessageReducer(min_messages=5, max_messages=8)
        messages = [SystemMessage(content="sys")] + [
            HumanMessage(content=f"q{i}") if i % 2 == 0
            else AIMessage(content=f"a{i}")
            for i in range(12)
        ]
        result = reducer.reduce(existing=messages)
        assert len(result.surviving) < len(messages)
        assert len(result.pruned) > 0

    def test_only_prunes_ai_and_human(self):
        reducer = MessageReducer(min_messages=3, max_messages=5)
        messages = [
            SystemMessage(content="sys"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
            HumanMessage(content="q3"),
            AIMessage(content="a3"),
        ]
        result = reducer.reduce(existing=messages)
        for msg in result.pruned:
            assert isinstance(msg, (AIMessage, HumanMessage))


# ── ToolMessage Cascade with LangChain Types ────────────────

class TestLangChainToolCascade:

    def test_prunes_linked_tool_messages(self):
        reducer = MessageReducer(min_messages=3, max_messages=5)
        messages = [
            SystemMessage(content="sys"),
            HumanMessage(content="search for cats"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "search", "args": {"q": "cats"}}],
            ),
            ToolMessage(content="results for cats", tool_call_id="call_1"),
            HumanMessage(content="thanks"),
            AIMessage(content="you're welcome"),
            HumanMessage(content="another"),
            AIMessage(content="response"),
        ]
        result = reducer.reduce(existing=messages)

        pruned_types = [type(m).__name__ for m in result.pruned]
        pruned_contents = [m.content for m in result.pruned]

        # If AIMessage with tool_calls was pruned, ToolMessage should be too
        if any(isinstance(m, AIMessage) and getattr(m, "tool_calls", None) for m in result.pruned):
            assert any(isinstance(m, ToolMessage) for m in result.pruned), (
                f"ToolMessage not cascade-pruned. Pruned: {pruned_types}"
            )

    def test_multiple_tool_calls(self):
        reducer = MessageReducer(min_messages=3, max_messages=5)
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "search", "args": {}},
                {"id": "call_2", "name": "calc", "args": {}},
            ],
        )
        messages = [
            SystemMessage(content="sys"),
            HumanMessage(content="multi-tool"),
            ai_msg,
            ToolMessage(content="search result", tool_call_id="call_1"),
            ToolMessage(content="calc result", tool_call_id="call_2"),
            HumanMessage(content="follow-up"),
            AIMessage(content="response"),
            HumanMessage(content="more"),
            AIMessage(content="more response"),
        ]
        result = reducer.reduce(existing=messages)

        if ai_msg in result.pruned:
            pruned_tool_call_ids = [
                m.tool_call_id for m in result.pruned if isinstance(m, ToolMessage)
            ]
            assert "call_1" in pruned_tool_call_ids
            assert "call_2" in pruned_tool_call_ids


# ── Mixed Input Types ───────────────────────────────────────

class TestMixedTypes:

    def test_mixed_dicts_and_langchain(self):
        """Reducer should handle a mix of dicts and LangChain objects."""
        reducer = MessageReducer(min_messages=3, max_messages=5)
        messages = [
            {"role": "system", "content": "sys", "id": "sys-1"},
            HumanMessage(content="lc-human"),
            {"role": "ai", "content": "dict-ai", "id": "a1"},
            AIMessage(content="lc-ai"),
            {"role": "human", "content": "dict-human", "id": "h2"},
            HumanMessage(content="another-lc"),
            AIMessage(content="final-ai"),
        ]
        result = reducer.reduce(existing=messages)
        assert len(result.surviving) + len(result.pruned) == len(messages)

    def test_dict_in_surviving_stays_dict(self):
        """Dicts should not be converted to LangChain objects."""
        reducer = MessageReducer(min_messages=5, max_messages=10)
        messages = [
            {"role": "human", "content": "hello", "id": "h1"},
            HumanMessage(content="world"),
        ]
        result = reducer.reduce(existing=messages)
        assert isinstance(result.surviving[0], dict)
        assert isinstance(result.surviving[1], HumanMessage)


# ── LangGraph Bridge with LangChain Types ───────────────────

class TestLangGraphBridgeLangChain:

    def test_bridge_with_langchain_messages(self):
        reducer = MessageReducer(min_messages=3, max_messages=5)
        fn = reducer.as_langgraph_reducer()

        existing = [
            SystemMessage(content="sys"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
        ]
        new = [
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
            HumanMessage(content="q3"),
            AIMessage(content="a3"),
        ]

        result = fn(existing, new)
        assert isinstance(result, list)
        assert len(result) <= 7
        # System message preserved
        assert isinstance(result[0], SystemMessage)


# ── Invariants ──────────────────────────────────────────────

class TestLangChainInvariants:

    def test_surviving_plus_pruned_equals_total(self):
        reducer = MessageReducer(min_messages=5, max_messages=10)
        messages = [SystemMessage(content="sys")] + [
            HumanMessage(content=f"q{i}") if i % 2 == 0
            else AIMessage(content=f"a{i}")
            for i in range(20)
        ]
        result = reducer.reduce(existing=messages)
        assert len(result.surviving) + len(result.pruned) == len(messages)
