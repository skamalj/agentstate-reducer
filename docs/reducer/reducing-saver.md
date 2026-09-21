# Any Checkpointer, Bounded: `ReducingSaver`

!!! success "New in agentstate-reducer 0.5.0"
    `ReducingSaver` wraps **any** LangGraph `BaseCheckpointSaver` and runs the reducer in its save path, the same way the [DynamoDB](../langgraph/dynamodb.md), [Cosmos DB](../langgraph/cosmosdb.md) and [Firestore](../langgraph/firestore.md) checkpointers do natively. PostgresSaver, SQLite, MongoDB, Redis, in-memory: one line.

```bash
pip install "agentstate-reducer[langgraph]"
```

```python
from langgraph.checkpoint.postgres import PostgresSaver
from agentstate_reducer import MessageReducer, ReducerConfig
from agentstate_reducer.langgraph import ReducingSaver

with PostgresSaver.from_conn_string(url) as pg:
    pg.setup()
    saver = ReducingSaver(pg, MessageReducer(config=ReducerConfig(max_messages=20)))
    graph = builder.compile(checkpointer=saver)
    graph.invoke(input, config={"configurable": {"thread_id": tid, "memory_namespace": ("memories", user_id)}})
```

## The problem it solves

Checkpoint storage grows on two axes, and the usual advice covers only one.

| Axis | Growth | Remedy |
|---|---|---|
| **How many checkpoints you keep** | one per step or per run | `prune(strategy="keep_latest")`, `delete_thread`, TTL |
| **How big each checkpoint is** | the messages channel is written whole on every step that touches it, so turn *n* stores all *n* messages: **quadratic** per thread | nothing built in |

Keep-latest deletes the old versions but the latest blob still holds the whole conversation. `ReducingSaver` bounds the second axis: every blob holds at most `max_messages` messages, so a thread's storage is linear in turns, and constant once you also prune. The pruned turns are not lost; they go to the reducer's [`on_prune` hook](long-term-memory.md), once each, with the `memory_namespace` from the run config.

Measured on PostgresSaver in the test that ships with the package: after ten turns with a window of six, the newest `checkpoint_blobs` row for the messages channel is no larger than the one written when the window first filled.

## How it behaves

The wrapper looks at the inner saver once, in the constructor:

| Inner saver | Behaviour |
|---|---|
| has no `reducer` attribute (PostgresSaver, SQLite, Mongo, Redis, in-memory, ...) | the wrapper reduces the messages channel in `put` and `aput` |
| has `reducer = None` (our three checkpointers built without one) | the wrapper **assigns its reducer to the inner saver** and passes every call through, so the reduction runs once, inside the saver |
| already holds the **same** reducer object, including another `ReducingSaver` | pass-through |
| holds a **different** reducer | `ValueError`. Two reducers keep two dedupe memories, so pruned turns would reach long-term memory twice |

`saver.passthrough`, `saver.reducer` and `saver.inner` tell you which case you got. Everything else, including the optional capabilities `copy_thread`, `delete_for_runs`, `prune` and delta-channel history, is delegated to the inner saver **only when it implements them**, so LangSmith Deployment's capability probe and the conformance suite see the inner saver's real capabilities. A wrapped `InMemorySaver` passes the full base conformance suite.

The namespace rule is the one every agentstate checkpointer uses: `config["configurable"]["memory_namespace"]` (or `ReducerConfig.namespace_key`), falling back to `("memories", thread_id)`. Both helpers are importable if you are writing your own saver: `agentstate_reducer.langgraph.memory_namespace` and `apply_reducer`.

## What it does not do

- It does not change what the model sees during the current run. The reduced list is what the **next** invoke loads.
- It only acts on steps that write the messages channel. In a chat graph that is every turn.
- It must not be used on a messages channel backed by `DeltaChannel`: the reducer replaces the channel value, which breaks delta reconstruction.
- It is not a substitute for `prune`. Use both: the wrapper bounds each checkpoint, `prune` bounds how many you keep.

## With an extractor

```python
from langgraph_memory import MemoryEngine
from agentstate_reducer import Background

engine = MemoryEngine(store, "anthropic:claude-sonnet-5")
reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(engine.on_prune)]))
saver = ReducingSaver(PostgresSaver.from_conn_string(url), reducer)
```

Same reducer, same hook, any saver. See [Plugging in an Extractor](extractors.md).
