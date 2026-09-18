"""Tests for ReducerConfig.on_prune hooks, reduce(namespace=...), and Background."""

import threading
import time

from agentstate_reducer import (
    DEFAULT_NAMESPACE_KEY,
    Background,
    MessageReducer,
    ReducerConfig,
)


def _msgs(n):
    out = [{"role": "system", "content": "sys", "id": "s"}]
    for i in range(n):
        out.append({"role": "human" if i % 2 == 0 else "ai", "content": f"m{i}", "id": f"m{i}"})
    return out


def test_hook_receives_pruned_and_namespace():
    seen = []
    cfg = ReducerConfig(min_messages=3, max_messages=5, on_prune=[lambda p, ns: seen.append((p, ns))])
    result = MessageReducer(config=cfg).reduce(existing=_msgs(8), namespace=("memories", "kamal"))
    assert len(seen) == 1
    pruned, ns = seen[0]
    assert pruned == result.pruned and pruned
    assert ns == ("memories", "kamal")


def test_hook_not_called_when_nothing_pruned():
    called = []
    cfg = ReducerConfig(max_messages=50, on_prune=[lambda p, ns: called.append(1)])
    MessageReducer(config=cfg).reduce(existing=_msgs(4), namespace="x")
    assert called == []


def test_namespace_defaults_to_none_for_old_callers():
    seen = []
    cfg = ReducerConfig(min_messages=3, max_messages=5, on_prune=[lambda p, ns: seen.append(ns)])
    MessageReducer(config=cfg).reduce(existing=_msgs(8))  # no namespace kwarg
    assert seen == [None]


def test_hooks_run_in_order_and_failure_is_isolated():
    order = []

    def bad(p, ns):
        order.append("bad")
        raise RuntimeError("boom")

    cfg = ReducerConfig(
        min_messages=3, max_messages=5,
        on_prune=[lambda p, ns: order.append("a"), bad, lambda p, ns: order.append("c")],
    )
    result = MessageReducer(config=cfg).reduce(existing=_msgs(8))
    assert order == ["a", "bad", "c"]
    assert result.pruned  # reduce still succeeded


def test_hook_runs_after_summary_and_sees_original_pruned():
    seen = {}
    cfg = ReducerConfig(
        min_messages=3, max_messages=5,
        summarize_fn=lambda p: "SUMMARY",
        inject_summary=True,
        on_prune=[lambda p, ns: seen.update(pruned=list(p))],
    )
    result = MessageReducer(config=cfg).reduce(existing=_msgs(8))
    assert result.summary == "SUMMARY"
    assert seen["pruned"] == result.pruned
    assert all(m.get("content") != "SUMMARY" for m in seen["pruned"])


def test_default_namespace_key():
    assert ReducerConfig().namespace_key == DEFAULT_NAMESPACE_KEY == "memory_namespace"
    assert ReducerConfig(namespace_key="tenant").namespace_key == "tenant"


# ── Background ────────────────────────────────────────────────────────────────


def test_background_runs_hook_off_thread_and_copies_list():
    seen = {}
    done = threading.Event()

    def fn(p, ns):
        seen["thread"] = threading.current_thread().name
        seen["pruned"] = p
        seen["ns"] = ns
        done.set()

    with Background(fn) as bg:
        original = [{"role": "human", "content": "x", "id": "x"}]
        bg(original, "ns1")
        assert done.wait(5)
        original.append("mutated")
    assert seen["thread"].startswith("on_prune")
    assert seen["pruned"] == [{"role": "human", "content": "x", "id": "x"}]
    assert seen["ns"] == "ns1"


def test_background_does_not_block_caller():
    release = threading.Event()

    def slow(p, ns):
        release.wait(5)

    bg = Background(slow, workers=1)
    t0 = time.perf_counter()
    bg([1], None)
    bg([2], None)
    assert time.perf_counter() - t0 < 0.5
    release.set()
    bg.close()


def test_background_drops_when_backlog_full():
    release = threading.Event()

    def slow(p, ns):
        release.wait(5)

    bg = Background(slow, workers=1, max_pending=2)
    bg([1], None)
    bg([2], None)
    bg([3], None)  # over max_pending -> dropped
    assert bg.dropped == 1
    release.set()
    bg.close()


def test_background_hook_exception_is_swallowed():
    def bad(p, ns):
        raise ValueError("nope")

    bg = Background(bad)
    bg([1], None)
    bg.close()  # would raise if exception propagated
    assert bg.dropped == 0


def test_background_after_close_drops():
    bg = Background(lambda p, ns: None)
    bg.close()
    bg([1], None)
    assert bg.dropped == 1


def test_background_integrates_with_reducer():
    got = []
    done = threading.Event()

    def fn(p, ns):
        got.append((len(p), ns))
        done.set()

    bg = Background(fn)
    cfg = ReducerConfig(min_messages=3, max_messages=5, on_prune=[bg])
    result = MessageReducer(config=cfg).reduce(existing=_msgs(8), namespace=("m", "u1"))
    assert done.wait(5)
    bg.close()
    assert got == [(len(result.pruned), ("m", "u1"))]


# ── exactly-once delivery ─────────────────────────────────────────────────────


def test_same_message_delivered_once_across_overlapping_reduces():
    seen = []
    cfg = ReducerConfig(min_messages=3, max_messages=5, on_prune=[lambda p, ns: seen.extend(m["id"] for m in p)])
    r = MessageReducer(config=cfg)
    msgs = _msgs(8)
    r.reduce(existing=msgs[:7])   # prunes some
    r.reduce(existing=msgs)       # overlapping list, prunes a superset
    assert len(seen) == len(set(seen))
    r2 = MessageReducer(config=cfg)          # fresh instance = fresh memory
    r2.reduce(existing=msgs)
    assert set(seen) <= set(m["id"] for m in msgs)


def test_hook_skipped_entirely_when_all_already_delivered():
    calls = []
    cfg = ReducerConfig(min_messages=3, max_messages=5, on_prune=[lambda p, ns: calls.append(len(p))])
    r = MessageReducer(config=cfg)
    r.reduce(existing=_msgs(8))
    r.reduce(existing=_msgs(8))   # identical -> nothing new
    assert calls == [calls[0]]


def test_messages_without_id_always_delivered():
    calls = []
    cfg = ReducerConfig(min_messages=3, max_messages=5, on_prune=[lambda p, ns: calls.append(len(p))])
    r = MessageReducer(config=cfg)
    noid = [{"role": "system", "content": "s"}] + [{"role": "human", "content": str(i)} for i in range(8)]
    r.reduce(existing=noid); r.reduce(existing=noid)
    assert len(calls) == 2 and calls[0] == calls[1]


def test_dedupe_can_be_disabled():
    calls = []
    cfg = ReducerConfig(min_messages=3, max_messages=5, dedupe_on_prune=False,
                        on_prune=[lambda p, ns: calls.append(len(p))])
    r = MessageReducer(config=cfg)
    r.reduce(existing=_msgs(8)); r.reduce(existing=_msgs(8))
    assert len(calls) == 2


def test_dedupe_window_is_bounded():
    cfg = ReducerConfig(min_messages=1, max_messages=2, preserve_first=False, dedupe_window=5,
                        on_prune=[lambda p, ns: None])
    r = MessageReducer(config=cfg)
    for i in range(50):
        r.reduce(existing=[{"role": "human", "content": "x", "id": f"id{i}"}] * 1 + [{"role": "ai", "content": "y", "id": f"ai{i}"}, {"role": "human", "content": "z", "id": f"h{i}"}])
    assert len(r._delivered) <= 5


def test_pruned_on_result_is_unfiltered_even_when_hooks_deduped():
    cfg = ReducerConfig(min_messages=3, max_messages=5, on_prune=[lambda p, ns: None])
    r = MessageReducer(config=cfg)
    a = r.reduce(existing=_msgs(8)); b = r.reduce(existing=_msgs(8))
    assert a.pruned == b.pruned and b.pruned
