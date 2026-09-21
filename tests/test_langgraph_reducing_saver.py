"""ReducingSaver: bounded checkpoints on any LangGraph saver, on_prune delivery, adoption rules, conformance."""
import asyncio
import os
from uuid import uuid4

import pytest

pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, END, MessagesState, StateGraph

from agentstate_reducer import MessageReducer, ReducerConfig
from agentstate_reducer.langgraph import ReducingSaver, apply_reducer, memory_namespace

MAX, MIN = 6, 4


def build_graph(saver):
    def echo(state: MessagesState):
        return {"messages": [AIMessage(content=f"reply to {state['messages'][-1].content}", id=str(uuid4()))]}

    b = StateGraph(MessagesState)
    b.add_node("echo", echo)
    b.add_edge(START, "echo")
    b.add_edge("echo", END)
    return b.compile(checkpointer=saver)


def reducer_with_sink(sink):
    def remember(pruned, namespace):
        sink.append((namespace, [m.id for m in pruned]))

    return MessageReducer(config=ReducerConfig(max_messages=MAX, min_messages=MIN, preserve_first=False, on_prune=[remember]))


def run_turns(graph, cfg, n):
    for i in range(n):
        graph.invoke({"messages": [HumanMessage(content=f"turn {i}", id=f"h{i}")]}, config=cfg)


# ---------------------------------------------------------------- in-memory saver

def test_bounded_checkpoints_and_exactly_once_on_prune():
    sink = []
    saver = ReducingSaver(InMemorySaver(), reducer_with_sink(sink))
    assert saver.passthrough is False
    graph = build_graph(saver)
    tid = uuid4().hex
    cfg = {"configurable": {"thread_id": tid, "memory_namespace": ("memories", "kamal")}}
    run_turns(graph, cfg, 8)  # 16 messages produced in total

    stored = saver.get_tuple(cfg).checkpoint["channel_values"]["messages"]
    assert len(stored) <= MAX
    assert stored[-1].content.startswith("reply to turn 7")

    delivered = [mid for _, ids in sink for mid in ids]
    assert delivered, "some turns must have been pruned"
    assert len(delivered) == len(set(delivered)), "each message id is delivered once"
    assert all(ns == ("memories", "kamal") for ns, _ in sink)
    # every produced message is either still stored or was delivered to the hook
    assert set(delivered) | {m.id for m in stored} == {f"h{i}" for i in range(8)} | {m.id for m in stored if m.type == "ai"} | set(delivered)


def test_namespace_fallback_is_thread_id():
    sink = []
    saver = ReducingSaver(InMemorySaver(), reducer_with_sink(sink))
    graph = build_graph(saver)
    tid = uuid4().hex
    run_turns(graph, {"configurable": {"thread_id": tid}}, 8)
    assert sink and all(ns == ("memories", tid) for ns, _ in sink)


def test_memory_namespace_and_apply_reducer_helpers():
    r = MessageReducer(config=ReducerConfig(max_messages=2, min_messages=1, preserve_first=False))
    assert memory_namespace(r, {"configurable": {"memory_namespace": "u1"}}) == "u1"
    assert memory_namespace(r, {"configurable": {"thread_id": "t"}}) == ("memories", "t")
    assert memory_namespace(r, None) is None
    cp = {"id": "x", "channel_values": {"messages": [HumanMessage("a", id="1"), AIMessage("b", id="2"), HumanMessage("c", id="3")]}}
    out = apply_reducer(r, cp, None)
    assert out is not cp and len(out["channel_values"]["messages"]) == 1 and len(cp["channel_values"]["messages"]) == 3
    assert apply_reducer(r, {"id": "y", "channel_values": {}}, None)["id"] == "y"


# ---------------------------------------------------------------- adoption rules

class ReducerAwareSaver(InMemorySaver):
    """Stand-in for the agentstate checkpointers: applies self.reducer itself in put."""

    def __init__(self):
        super().__init__()
        self.reducer = None
        self.puts = 0

    def put(self, config, checkpoint, metadata, new_versions):
        self.puts += 1
        return super().put(config, apply_reducer(self.reducer, checkpoint, config), metadata, new_versions)


def test_adopts_reducer_when_inner_has_none():
    sink = []
    reducer = reducer_with_sink(sink)
    inner = ReducerAwareSaver()
    saver = ReducingSaver(inner, reducer)
    assert saver.passthrough is True and inner.reducer is reducer and saver.reducer is reducer
    graph = build_graph(saver)
    cfg = {"configurable": {"thread_id": uuid4().hex}}
    run_turns(graph, cfg, 8)
    assert len(saver.get_tuple(cfg).checkpoint["channel_values"]["messages"]) <= MAX
    delivered = [mid for _, ids in sink for mid in ids]
    assert delivered and len(delivered) == len(set(delivered)), "reduced once, delivered once"


def test_same_reducer_is_passthrough_and_different_reducer_raises():
    reducer = reducer_with_sink([])
    inner = ReducerAwareSaver()
    inner.reducer = reducer
    assert ReducingSaver(inner, reducer).passthrough is True
    with pytest.raises(ValueError, match="different reducer"):
        ReducingSaver(inner, reducer_with_sink([]))


def test_double_wrap_follows_the_same_rule():
    reducer = reducer_with_sink([])
    first = ReducingSaver(InMemorySaver(), reducer)
    second = ReducingSaver(first, reducer)
    assert second.passthrough is True and second.inner is first
    with pytest.raises(ValueError, match="different reducer"):
        ReducingSaver(first, reducer_with_sink([]))


def test_reducer_required():
    with pytest.raises(ValueError):
        ReducingSaver(InMemorySaver(), None)


# ---------------------------------------------------------------- capability exposure

class PruningSaver(InMemorySaver):
    """InMemorySaver implements only the base capabilities; this one adds prune so mirroring can be checked."""

    def prune(self, thread_ids, *, strategy="keep_latest"):
        for t in thread_ids:
            self.delete_thread(t)

    async def aprune(self, thread_ids, *, strategy="keep_latest"):
        self.prune(thread_ids, strategy=strategy)


def test_optional_capabilities_mirror_inner():
    from langgraph.checkpoint.conformance.capabilities import Capability, DetectedCapabilities

    pruning = ReducingSaver(PruningSaver(), reducer_with_sink([]))
    basic = ReducingSaver(InMemorySaver(), reducer_with_sink([]))
    assert Capability.PRUNE in DetectedCapabilities.from_instance(pruning).detected
    assert Capability.PRUNE not in DetectedCapabilities.from_instance(basic).detected
    assert Capability.COPY_THREAD not in DetectedCapabilities.from_instance(pruning).detected
    assert type(pruning) is not type(basic)
    assert isinstance(pruning, ReducingSaver) and isinstance(basic, ReducingSaver)
    pruning.prune(["t1"])  # delegates without error


def test_conformance_full_on_wrapped_inmemory():
    from langgraph.checkpoint.conformance import checkpointer_test, validate

    @checkpointer_test(name="ReducingSaver[InMemorySaver]")
    async def factory():
        yield ReducingSaver(InMemorySaver(), MessageReducer(config=ReducerConfig(max_messages=1000)))

    report = asyncio.run(validate(factory))
    report.print_report()
    assert report.passed_all_base(), "wrapped InMemorySaver must still pass every base test"


# ---------------------------------------------------------------- PostgresSaver (real database)

PG_URL = os.environ.get("REDUCER_PG_URL")  # e.g. postgresql://postgres:postgres@localhost:5433/postgres; opt-in


@pytest.mark.skipif(not PG_URL, reason="set REDUCER_PG_URL to run against PostgreSQL")
def test_postgres_saver_blobs_stay_bounded():
    from langgraph.checkpoint.postgres import PostgresSaver
    import psycopg

    sink = []
    with PostgresSaver.from_conn_string(PG_URL) as inner:
        inner.setup()
        saver = ReducingSaver(inner, reducer_with_sink(sink))
        graph = build_graph(saver)
        tid = uuid4().hex
        cfg = {"configurable": {"thread_id": tid, "memory_namespace": ("memories", "kamal")}}
        run_turns(graph, cfg, 10)
        stored = saver.get_tuple(cfg).checkpoint["channel_values"]["messages"]
        assert len(stored) <= MAX
        with psycopg.connect(PG_URL) as conn:
            sizes = conn.execute(
                "SELECT octet_length(blob) FROM checkpoint_blobs WHERE thread_id=%s AND channel='messages' ORDER BY version",
                (tid,),
            ).fetchall()
        assert sizes, "messages blobs written"
        # bounded: the last blob is not larger than ~2x the blob written when the window first filled
        first_full = sizes[MAX - 1][0]
        assert sizes[-1][0] <= 2 * first_full, sizes
        delivered = [mid for _, ids in sink for mid in ids]
        assert delivered and len(delivered) == len(set(delivered))
        inner.delete_thread(tid)
