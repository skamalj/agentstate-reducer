"""
Tests for MessageReducer using plain dicts.

Verifies that the reducer works without any LangChain dependency.
"""

import pytest

from agentstate_reducer import MessageReducer, ReducerConfig, ReducerResult


# ── Helpers ──────────────────────────────────────────────────

def _sys(content="You are helpful"):
    return {"role": "system", "content": content, "id": "sys-1"}

def _human(content, msg_id="h1"):
    return {"role": "human", "content": content, "id": msg_id}

def _ai(content, msg_id="a1", tool_calls=None):
    msg = {"role": "ai", "content": content, "id": msg_id}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg

def _tool(content, tool_call_id, msg_id="t1"):
    return {"role": "tool", "content": content, "id": msg_id, "tool_call_id": tool_call_id}


# ── Basic Behavior ───────────────────────────────────────────

class TestBasicReducer:

    def test_no_pruning_under_threshold(self):
        reducer = MessageReducer(min_messages=5, max_messages=10)
        messages = [_human(f"msg-{i}", f"h{i}") for i in range(8)]
        result = reducer.reduce(existing=messages)
        assert len(result.surviving) == 8
        assert len(result.pruned) == 0

    def test_no_pruning_when_max_is_none(self):
        reducer = MessageReducer(min_messages=5, max_messages=None)
        messages = [_human(f"msg-{i}", f"h{i}") for i in range(100)]
        result = reducer.reduce(existing=messages)
        assert len(result.surviving) == 100
        assert len(result.pruned) == 0

    def test_concatenation(self):
        reducer = MessageReducer(min_messages=5, max_messages=20)
        existing = [_human("old", "h1")]
        new = [_human("new", "h2")]
        result = reducer.reduce(existing=existing, new=new)
        assert len(result.surviving) == 2
        assert result.surviving[0]["content"] == "old"
        assert result.surviving[1]["content"] == "new"

    def test_empty_inputs(self):
        reducer = MessageReducer(min_messages=5, max_messages=10)
        result = reducer.reduce(existing=None, new=None)
        assert result.surviving == []
        assert result.pruned == []

    def test_returns_reducer_result(self):
        reducer = MessageReducer(min_messages=5, max_messages=10)
        result = reducer.reduce(existing=[])
        assert isinstance(result, ReducerResult)


# ── Pruning Behavior ────────────────────────────────────────

class TestPruning:

    def test_prunes_to_min_messages(self):
        reducer = MessageReducer(min_messages=5, max_messages=10)
        messages = [_sys()] + [
            _human(f"msg-{i}", f"h{i}") if i % 2 == 0 else _ai(f"resp-{i}", f"a{i}")
            for i in range(15)
        ]
        result = reducer.reduce(existing=messages)
        # Should have pruned down to approximately min_messages
        assert len(result.surviving) <= len(messages)
        assert len(result.pruned) > 0
        assert len(result.surviving) + len(result.pruned) == len(messages)

    def test_preserves_system_message_at_index_0(self):
        reducer = MessageReducer(min_messages=3, max_messages=5)
        messages = [
            _sys(),
            _human("q1", "h1"),
            _ai("a1", "a1"),
            _human("q2", "h2"),
            _ai("a2", "a2"),
            _human("q3", "h3"),
            _ai("a3", "a3"),
        ]
        result = reducer.reduce(existing=messages)
        # System message must survive
        assert result.surviving[0]["role"] == "system"
        assert result.surviving[0]["id"] == "sys-1"

    def test_does_not_preserve_first_when_disabled(self):
        config = ReducerConfig(min_messages=2, max_messages=4, preserve_first=False)
        reducer = MessageReducer(config=config)
        messages = [
            _human("q1", "h1"),
            _ai("a1", "a1"),
            _human("q2", "h2"),
            _ai("a2", "a2"),
            _human("q3", "h3"),
        ]
        result = reducer.reduce(existing=messages)
        # First message can be pruned
        assert len(result.surviving) < len(messages)

    def test_only_prunes_ai_and_human_roles(self):
        reducer = MessageReducer(min_messages=2, max_messages=4)
        messages = [
            _sys(),
            {"role": "function", "content": "fn-result", "id": "f1"},
            _human("q1", "h1"),
            _ai("a1", "a1"),
            _human("q2", "h2"),
        ]
        result = reducer.reduce(existing=messages)
        # System and function messages should survive
        surviving_roles = [m["role"] for m in result.surviving]
        assert "system" in surviving_roles
        pruned_roles = [m["role"] for m in result.pruned]
        assert "system" not in pruned_roles
        assert "function" not in pruned_roles


# ── ToolMessage Cascade ─────────────────────────────────────

class TestToolMessageCascade:

    def test_prunes_linked_tool_messages(self):
        reducer = MessageReducer(min_messages=3, max_messages=5)
        messages = [
            _sys(),
            _human("search for cats", "h1"),
            _ai("", "a1", tool_calls=[{"id": "call_1", "name": "search", "args": {}}]),
            _tool("search results for cats", "call_1", "t1"),
            _human("thanks", "h2"),
            _ai("you're welcome", "a2"),
            _human("another question", "h3"),
            _ai("another answer", "a3"),
        ]
        result = reducer.reduce(existing=messages)

        # If AIMessage a1 is pruned, ToolMessage t1 must also be pruned
        pruned_ids = {m["id"] for m in result.pruned}
        if "a1" in pruned_ids:
            assert "t1" in pruned_ids, "ToolMessage linked to pruned AIMessage should be cascade-pruned"

    def test_no_cascade_when_disabled(self):
        config = ReducerConfig(
            min_messages=3, max_messages=5, cascade_tool_messages=False
        )
        reducer = MessageReducer(config=config)
        messages = [
            _sys(),
            _human("q1", "h1"),
            _ai("", "a1", tool_calls=[{"id": "call_1", "name": "search", "args": {}}]),
            _tool("result", "call_1", "t1"),
            _human("q2", "h2"),
            _ai("a2", "a2"),
            _human("q3", "h3"),
            _ai("a3", "a3"),
        ]
        result = reducer.reduce(existing=messages)
        pruned_ids = {m["id"] for m in result.pruned}
        # Even if a1 is pruned, t1 should NOT be cascade-pruned
        if "a1" in pruned_ids:
            assert "t1" not in pruned_ids

    def test_multiple_tool_calls_cascade(self):
        reducer = MessageReducer(min_messages=3, max_messages=5)
        messages = [
            _sys(),
            _human("multi-tool", "h1"),
            _ai("", "a1", tool_calls=[
                {"id": "call_1", "name": "search", "args": {}},
                {"id": "call_2", "name": "calc", "args": {}},
            ]),
            _tool("search result", "call_1", "t1"),
            _tool("calc result", "call_2", "t2"),
            _human("follow-up", "h2"),
            _ai("response", "a2"),
            _human("more", "h3"),
            _ai("more response", "a3"),
        ]
        result = reducer.reduce(existing=messages)
        pruned_ids = {m["id"] for m in result.pruned}
        # Both tool messages should be cascade-pruned if a1 is pruned
        if "a1" in pruned_ids:
            assert "t1" in pruned_ids
            assert "t2" in pruned_ids


# ── Summarization ───────────────────────────────────────────

class TestSummarization:

    def test_summarize_fn_called_with_pruned(self):
        captured = {}

        def mock_summarize(pruned_messages):
            captured["messages"] = pruned_messages
            return f"Summary of {len(pruned_messages)} messages"

        config = ReducerConfig(
            min_messages=3, max_messages=5, summarize_fn=mock_summarize
        )
        reducer = MessageReducer(config=config)
        messages = [_sys()] + [
            _human(f"q{i}", f"h{i}") if i % 2 == 0 else _ai(f"a{i}", f"a{i}")
            for i in range(10)
        ]
        result = reducer.reduce(existing=messages)

        assert len(result.pruned) > 0
        assert "messages" in captured
        assert len(captured["messages"]) == len(result.pruned)
        assert result.summary is not None
        assert "Summary of" in result.summary

    def test_no_summary_when_no_pruning(self):
        config = ReducerConfig(
            min_messages=5, max_messages=20,
            summarize_fn=lambda msgs: "should not be called"
        )
        reducer = MessageReducer(config=config)
        result = reducer.reduce(existing=[_human("hello", "h1")])
        assert result.summary is None

    def test_summarize_fn_failure_does_not_crash(self):
        def failing_summarize(msgs):
            raise RuntimeError("LLM unavailable")

        config = ReducerConfig(
            min_messages=3, max_messages=5, summarize_fn=failing_summarize
        )
        reducer = MessageReducer(config=config)
        messages = [_sys()] + [
            _human(f"q{i}", f"h{i}") for i in range(10)
        ]
        # Should not raise
        result = reducer.reduce(existing=messages)
        assert result.summary is None
        assert len(result.pruned) > 0


# ── LangGraph Reducer Bridge ────────────────────────────────

class TestLangGraphBridge:

    def test_as_langgraph_reducer_returns_callable(self):
        reducer = MessageReducer(min_messages=5, max_messages=10)
        fn = reducer.as_langgraph_reducer()
        assert callable(fn)

    def test_as_langgraph_reducer_signature(self):
        reducer = MessageReducer(min_messages=3, max_messages=5)
        fn = reducer.as_langgraph_reducer()

        existing = [_sys(), _human("q1", "h1"), _ai("a1", "a1")]
        new = [_human("q2", "h2"), _ai("a2", "a2"), _human("q3", "h3"), _ai("a3", "a3")]

        result = fn(existing, new)
        assert isinstance(result, list)
        # Should have pruned something since 7 > max_messages=5
        assert len(result) <= 7

    def test_as_langgraph_reducer_handles_none(self):
        reducer = MessageReducer(min_messages=5, max_messages=10)
        fn = reducer.as_langgraph_reducer()
        result = fn(None, None)
        assert result == []


# ── Config Object ────────────────────────────────────────────

class TestReducerConfig:

    def test_config_overrides_constructor_params(self):
        config = ReducerConfig(min_messages=42, max_messages=100)
        reducer = MessageReducer(min_messages=1, max_messages=2, config=config)
        assert reducer.min_messages == 42
        assert reducer.max_messages == 100

    def test_repr(self):
        reducer = MessageReducer(min_messages=10, max_messages=20)
        r = repr(reducer)
        assert "min_messages=10" in r
        assert "max_messages=20" in r


# ── Role Aliases ────────────────────────────────────────────

class TestRoleAliases:
    """
    Verify that role aliases (user→human, agent→ai, assistant→ai) are treated
    identically to their canonical counterparts for pruning purposes.
    """

    def test_user_role_pruned_like_human(self):
        """Dicts with role='user' (OpenAI format) should be pruned like 'human'."""
        reducer = MessageReducer(min_messages=3, max_messages=5)
        messages = [
            _sys(),
            {"role": "user", "content": "q1", "id": "u1"},
            {"role": "agent", "content": "a1", "id": "ag1"},
            {"role": "user", "content": "q2", "id": "u2"},
            {"role": "agent", "content": "a2", "id": "ag2"},
            {"role": "user", "content": "q3", "id": "u3"},
            {"role": "agent", "content": "a3", "id": "ag3"},
        ]
        result = reducer.reduce(existing=messages)
        assert len(result.pruned) > 0, "Expected pruning to occur"
        # Only user/agent messages should be in pruned (not system)
        for m in result.pruned:
            assert m["role"] in ("user", "agent"), (
                f"Unexpected role pruned: {m['role']}"
            )

    def test_agent_role_pruned_like_ai(self):
        """Dicts with role='agent' should be pruned like 'ai'."""
        reducer = MessageReducer(min_messages=2, max_messages=4)
        messages = [
            _sys(),
            {"role": "agent", "content": "resp1", "id": "ag1"},
            {"role": "human", "content": "q2", "id": "h2"},
            {"role": "agent", "content": "resp2", "id": "ag2"},
            {"role": "human", "content": "q3", "id": "h3"},
        ]
        result = reducer.reduce(existing=messages)
        assert len(result.pruned) > 0
        pruned_ids = {m["id"] for m in result.pruned}
        assert "ag1" in pruned_ids, "Oldest 'agent' message should be pruned"

    def test_assistant_role_pruned_like_ai(self):
        """Dicts with role='assistant' (OpenAI format) should be pruned like 'ai'."""
        reducer = MessageReducer(min_messages=2, max_messages=4)
        messages = [
            _sys(),
            {"role": "user", "content": "q1", "id": "u1"},
            {"role": "assistant", "content": "a1", "id": "as1"},
            {"role": "user", "content": "q2", "id": "u2"},
            {"role": "assistant", "content": "a2", "id": "as2"},
            {"role": "user", "content": "q3", "id": "u3"},
        ]
        result = reducer.reduce(existing=messages)
        assert len(result.pruned) > 0
        for m in result.pruned:
            assert m["role"] in ("user", "assistant"), (
                f"Unexpected role pruned: {m['role']}"
            )

    def test_type_key_agent_alias(self):
        """Dicts using 'type' key instead of 'role' should also be normalised."""
        reducer = MessageReducer(min_messages=2, max_messages=4)
        messages = [
            {"type": "system", "content": "sys", "id": "sys-1"},
            {"type": "user", "content": "q1", "id": "u1"},
            {"type": "agent", "content": "a1", "id": "ag1"},
            {"type": "user", "content": "q2", "id": "u2"},
            {"type": "agent", "content": "a2", "id": "ag2"},
            {"type": "user", "content": "q3", "id": "u3"},
        ]
        result = reducer.reduce(existing=messages)
        assert len(result.pruned) > 0
        pruned_ids = {m["id"] for m in result.pruned}
        # system message must never be pruned
        assert "sys-1" not in pruned_ids

    def test_mixed_canonical_and_alias_roles(self):
        """Canonical ('ai', 'human') and alias ('agent', 'user') roles should
        all be candidates for pruning in the same message list."""
        reducer = MessageReducer(min_messages=3, max_messages=6)
        messages = [
            _sys(),
            _human("q1", "h1"),                                    # canonical human
            {"role": "agent", "content": "a1", "id": "ag1"},       # alias ai
            {"role": "user", "content": "q2", "id": "u2"},         # alias human
            _ai("a2", "a2"),                                        # canonical ai
            {"role": "assistant", "content": "a3", "id": "as3"},   # alias ai
            _human("q4", "h4"),
            _ai("a4", "a4"),
        ]
        result = reducer.reduce(existing=messages)
        assert len(result.surviving) + len(result.pruned) == len(messages)
        assert len(result.pruned) > 0
        # System message always survives
        assert result.surviving[0]["role"] == "system"


# ── Invariants ──────────────────────────────────────────────

class TestInvariants:

    def test_surviving_plus_pruned_equals_total(self):
        """Key invariant: no messages are lost or duplicated."""
        reducer = MessageReducer(min_messages=5, max_messages=10)
        messages = [_sys()] + [
            _human(f"q{i}", f"h{i}") if i % 2 == 0 else _ai(f"a{i}", f"a{i}")
            for i in range(20)
        ]
        result = reducer.reduce(existing=messages)
        assert len(result.surviving) + len(result.pruned) == len(messages)

    def test_order_preserved(self):
        """Surviving messages should maintain their original relative order."""
        reducer = MessageReducer(min_messages=5, max_messages=10)
        messages = [_sys()] + [
            _human(f"q{i}", f"h{i}") for i in range(15)
        ]
        result = reducer.reduce(existing=messages)

        surviving_ids = [m["id"] for m in result.surviving]
        # Check that the order is preserved (each ID should come after the previous)
        for i in range(1, len(surviving_ids)):
            orig_idx_prev = next(
                j for j, m in enumerate(messages) if m["id"] == surviving_ids[i - 1]
            )
            orig_idx_curr = next(
                j for j, m in enumerate(messages) if m["id"] == surviving_ids[i]
            )
            assert orig_idx_prev < orig_idx_curr, (
                f"Order violated: {surviving_ids[i-1]} came before {surviving_ids[i]} "
                f"in surviving but not in original"
            )
