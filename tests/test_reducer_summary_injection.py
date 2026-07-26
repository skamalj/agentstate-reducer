"""
Tests for optional summary injection (human summary + ai "OK" pair).

- summary is always returned on ReducerResult.summary
- injection is opt-in (inject_summary)
- injected block = [human summary, ai "OK"], placed IN PLACE of the pruned block
  (after preserve_first, before the retained recent tail) — never at the very start
- because the pair are ordinary human/ai messages at the front, the next prune
  rolls them into the new summary: always exactly one pair, no accumulation
"""

from agentstate_reducer import MessageReducer, ReducerConfig


def summarize(pruned):
    return f"summary of {len(pruned)} messages"


def build(n_pairs):
    msgs = [{"role": "system", "content": "you are helpful"}]
    for i in range(n_pairs):
        msgs.append({"role": "human", "content": f"msg {i}"})
        msgs.append({"role": "ai", "content": f"reply {i}"})
    return msgs


def is_human_summary(m):
    return isinstance(m, dict) and m.get("role") == "human" and "summary of" in m.get("content", "")


def is_ack(m):
    return isinstance(m, dict) and m.get("role") == "ai" and m.get("content") == "OK"


class TestSummaryReturnedButNotInjectedByDefault:
    def test_summary_always_returned(self):
        r = MessageReducer(config=ReducerConfig(min_messages=4, max_messages=6, summarize_fn=summarize))
        result = r.reduce(existing=build(10))
        assert result.summary == "summary of " + str(len(result.pruned)) + " messages"

    def test_not_injected_without_flag(self):
        r = MessageReducer(config=ReducerConfig(min_messages=4, max_messages=6, summarize_fn=summarize))
        result = r.reduce(existing=build(10))
        assert not any(is_human_summary(m) for m in result.surviving)


class TestPairInjectionPlacement:
    def test_injects_human_ai_pair(self):
        r = MessageReducer(config=ReducerConfig(
            min_messages=4, max_messages=6, summarize_fn=summarize, inject_summary=True))
        result = r.reduce(existing=build(10))
        # exactly one human summary + one ai OK, adjacent
        hsum = [i for i, m in enumerate(result.surviving) if is_human_summary(m)]
        assert len(hsum) == 1
        assert is_ack(result.surviving[hsum[0] + 1])

    def test_system_stays_first_summary_second(self):
        r = MessageReducer(config=ReducerConfig(
            min_messages=4, max_messages=6, summarize_fn=summarize, inject_summary=True))
        result = r.reduce(existing=build(10))
        assert result.surviving[0] == {"role": "system", "content": "you are helpful"}
        assert is_human_summary(result.surviving[1])
        assert is_ack(result.surviving[2])

    def test_alternation_across_injected_block(self):
        r = MessageReducer(config=ReducerConfig(
            min_messages=4, max_messages=6, summarize_fn=summarize, inject_summary=True))
        result = r.reduce(existing=build(10))
        # system -> human(summary) -> ai(OK) -> ... must alternate through the block
        roles = [m["role"] for m in result.surviving[:3]]
        assert roles == ["system", "human", "ai"]

    def test_recent_tail_after_pair(self):
        r = MessageReducer(config=ReducerConfig(
            min_messages=4, max_messages=6, summarize_fn=summarize, inject_summary=True))
        msgs = build(10)  # newest is {"role": "ai", "content": "reply 9"}
        result = r.reduce(existing=msgs)
        assert result.surviving[-1] == {"role": "ai", "content": "reply 9"}

    def test_no_system_message_pair_at_start(self):
        # A conversation with no system message: with preserve_first=False the
        # pair leads (nothing structurally kept ahead of the pruned block).
        msgs = []
        for i in range(10):
            msgs.append({"role": "human", "content": f"msg {i}"})
            msgs.append({"role": "ai", "content": f"reply {i}"})
        r = MessageReducer(config=ReducerConfig(
            min_messages=4, max_messages=6, summarize_fn=summarize,
            inject_summary=True, preserve_first=False))
        result = r.reduce(existing=msgs)
        assert is_human_summary(result.surviving[0])
        assert is_ack(result.surviving[1])


class TestNoAccumulation:
    def test_pair_rolls_forward_single(self):
        cfg = ReducerConfig(min_messages=4, max_messages=6, summarize_fn=summarize, inject_summary=True)
        r = MessageReducer(config=cfg)

        first = r.reduce(existing=build(10))
        assert sum(1 for m in first.surviving if is_human_summary(m)) == 1

        # feed surviving (with a summary pair) + more messages back in
        more = []
        for i in range(6):
            more.append({"role": "human", "content": f"new {i}"})
            more.append({"role": "ai", "content": f"newreply {i}"})
        second = r.reduce(existing=first.surviving, new=more)

        # still exactly one summary pair — the prior pair was pruned & rolled in
        assert sum(1 for m in second.surviving if is_human_summary(m)) == 1
        assert sum(1 for m in second.surviving if is_ack(m)) == 1

    def test_prior_pair_fed_into_next_summarize(self):
        captured = {}

        def capturing(pruned):
            captured["input"] = list(pruned)
            return "rolled"

        cfg = ReducerConfig(min_messages=4, max_messages=6, summarize_fn=capturing, inject_summary=True)
        r = MessageReducer(config=cfg)
        first = r.reduce(existing=build(10))
        more = []
        for i in range(6):
            more.append({"role": "human", "content": f"new {i}"})
            more.append({"role": "ai", "content": f"newreply {i}"})
        r.reduce(existing=first.surviving, new=more)
        # the prior human-summary was pruned and passed into the next summarize call
        assert any(is_human_summary(m) for m in captured["input"])


class TestCustomFactory:
    def test_single_message_factory(self):
        def one_msg(text, count):
            return [{"role": "system", "content": f"[{count}] {text}"}]

        cfg = ReducerConfig(min_messages=4, max_messages=6, summarize_fn=summarize,
                            inject_summary=True, summary_message_factory=one_msg)
        result = MessageReducer(config=cfg).reduce(existing=build(10))
        injected = [m for m in result.surviving if m.get("role") == "system" and m["content"].startswith("[")]
        assert len(injected) == 1
