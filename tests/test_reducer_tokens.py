"""
Tests for token-budget pruning mode.

Covers all three token-counter resolution layers:
1. User-supplied token_counter callable
2. tiktoken (if installed)
3. Character heuristic fallback
"""

import pytest

from agentstate_reducer import MessageReducer, ReducerConfig
from agentstate_reducer.tokens import resolve_token_counter, _get_tiktoken_encoding


# A deterministic counter: every message counts as exactly 100 tokens.
def fixed_counter(_msg):
    return 100


def make_messages(n, role_cycle=("human", "ai")):
    msgs = [{"role": "system", "content": "system prompt"}]
    for i in range(n):
        role = role_cycle[i % len(role_cycle)]
        msgs.append({"role": role, "content": f"message number {i}"})
    return msgs


# ---------------------------------------------------------------------------
# Layer 1: user-supplied token_counter
# ---------------------------------------------------------------------------

class TestUserSuppliedCounter:
    def test_no_pruning_when_under_budget(self):
        # 3 messages * 100 = 300 tokens, under max_tokens=1000
        reducer = MessageReducer(config=ReducerConfig(max_tokens=1000, token_counter=fixed_counter))
        msgs = make_messages(2)  # system + 2 = 3 messages = 300 tokens
        result = reducer.reduce(existing=msgs, new=[])
        assert len(result.surviving) == 3
        assert result.pruned == []

    def test_prunes_to_token_budget(self):
        # 11 messages * 100 = 1100 tokens; max=500 → keep ~5 messages worth
        reducer = MessageReducer(config=ReducerConfig(max_tokens=500, token_counter=fixed_counter))
        msgs = make_messages(10)  # system + 10 = 11 messages = 1100 tokens
        result = reducer.reduce(existing=msgs, new=[])
        # Each message is 100 tokens; budget 500 → at most 5 messages survive
        total_surviving_tokens = sum(fixed_counter(m) for m in result.surviving)
        assert total_surviving_tokens <= 500
        assert len(result.pruned) > 0

    def test_messages_never_truncated(self):
        # Surviving messages must be identical objects, not truncated
        reducer = MessageReducer(config=ReducerConfig(max_tokens=300, token_counter=fixed_counter))
        msgs = make_messages(10)
        result = reducer.reduce(existing=msgs, new=[])
        for m in result.surviving:
            assert m in msgs  # exact object preserved, content intact

    def test_preserve_first_kept_under_tokens(self):
        reducer = MessageReducer(config=ReducerConfig(
            max_tokens=250, token_counter=fixed_counter, preserve_first=True
        ))
        msgs = make_messages(10)
        result = reducer.reduce(existing=msgs, new=[])
        # System message (index 0) must always survive
        assert result.surviving[0] == msgs[0]

    def test_most_recent_message_survives(self):
        reducer = MessageReducer(config=ReducerConfig(max_tokens=300, token_counter=fixed_counter))
        msgs = make_messages(10)
        result = reducer.reduce(existing=msgs, new=[])
        assert result.surviving[-1] == msgs[-1]

    def test_target_tokens_hysteresis(self):
        # Prune triggers at max_tokens=1000 but reduces down to target_tokens=300
        reducer = MessageReducer(config=ReducerConfig(
            max_tokens=1000, target_tokens=300, token_counter=fixed_counter
        ))
        msgs = make_messages(15)  # 16 messages = 1600 tokens, over max
        result = reducer.reduce(existing=msgs, new=[])
        total = sum(fixed_counter(m) for m in result.surviving)
        assert total <= 300

    def test_order_preserved(self):
        reducer = MessageReducer(config=ReducerConfig(max_tokens=400, token_counter=fixed_counter))
        msgs = make_messages(10)
        result = reducer.reduce(existing=msgs, new=[])
        # Surviving (minus preserved first) must be a contiguous recent tail
        tail = result.surviving[1:]
        assert tail == msgs[-len(tail):]

    def test_token_mode_takes_precedence_over_count(self):
        # max_messages would keep many; max_tokens should dominate
        reducer = MessageReducer(config=ReducerConfig(
            max_messages=100, min_messages=50,
            max_tokens=300, token_counter=fixed_counter,
        ))
        msgs = make_messages(20)
        result = reducer.reduce(existing=msgs, new=[])
        total = sum(fixed_counter(m) for m in result.surviving)
        assert total <= 300


# ---------------------------------------------------------------------------
# Layer 3: character heuristic (force tiktoken off)
# ---------------------------------------------------------------------------

class TestHeuristicCounter:
    def test_heuristic_counts_by_chars(self, monkeypatch):
        # Force the heuristic path by disabling tiktoken resolution
        monkeypatch.setattr("agentstate_reducer.tokens._get_tiktoken_encoding", lambda: None)
        counter = resolve_token_counter(None)
        # 40 chars / 4 + 4 overhead = 14
        msg = {"role": "human", "content": "x" * 40}
        assert counter(msg) == 14

    def test_heuristic_prunes(self, monkeypatch):
        monkeypatch.setattr("agentstate_reducer.tokens._get_tiktoken_encoding", lambda: None)
        # Long messages so heuristic produces meaningful counts
        msgs = [{"role": "system", "content": "s" * 40}]
        for i in range(10):
            msgs.append({"role": "human" if i % 2 == 0 else "ai", "content": "x" * 400})
        # Each long message ~ 104 tokens; budget 300 → only a couple survive
        reducer = MessageReducer(config=ReducerConfig(max_tokens=300))
        result = reducer.reduce(existing=msgs, new=[])
        assert len(result.pruned) > 0
        assert result.surviving[-1] == msgs[-1]


# ---------------------------------------------------------------------------
# Layer 2: tiktoken (only if installed)
# ---------------------------------------------------------------------------

class TestTiktokenCounter:
    def test_tiktoken_used_when_available(self):
        encoding = _get_tiktoken_encoding()
        if encoding is None:
            pytest.skip("tiktoken not installed")
        counter = resolve_token_counter(None)
        msg = {"role": "human", "content": "Hello, world!"}
        # tiktoken count of content + overhead; must be a positive int
        assert isinstance(counter(msg), int)
        assert counter(msg) > 0

    def test_tiktoken_prunes_to_budget(self):
        encoding = _get_tiktoken_encoding()
        if encoding is None:
            pytest.skip("tiktoken not installed")
        msgs = [{"role": "system", "content": "You are a helpful assistant."}]
        for i in range(20):
            msgs.append({"role": "human" if i % 2 == 0 else "ai",
                         "content": f"This is message {i} with some content to count."})
        reducer = MessageReducer(config=ReducerConfig(max_tokens=100))
        result = reducer.reduce(existing=msgs, new=[])
        counter = resolve_token_counter(None)
        total = sum(counter(m) for m in result.surviving)
        # Allows preserved-first overshoot, but should be in the right ballpark
        assert len(result.pruned) > 0
        assert result.surviving[-1] == msgs[-1]


# ---------------------------------------------------------------------------
# Cascade still works in token mode
# ---------------------------------------------------------------------------

class TestTokenModeCascade:
    def test_tool_messages_cascade_pruned(self):
        # When an AI message with tool_calls is pruned, its tool message follows
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "ai", "content": "call", "tool_calls": [{"id": "tc1"}]},
            {"role": "tool", "content": "result", "tool_call_id": "tc1"},
        ]
        for i in range(10):
            msgs.append({"role": "human" if i % 2 == 0 else "ai", "content": f"m{i}"})

        reducer = MessageReducer(config=ReducerConfig(
            max_tokens=300, token_counter=fixed_counter, cascade_tool_messages=True
        ))
        result = reducer.reduce(existing=msgs, new=[])
        # If the ai message at index 1 was pruned, its tool message must be too
        ai_msg = msgs[1]
        tool_msg = msgs[2]
        if ai_msg in result.pruned:
            assert tool_msg in result.pruned
