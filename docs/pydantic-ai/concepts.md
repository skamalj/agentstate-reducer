# StepStore & History

The PydanticAI family is built on a deliberately tiny contract: an async key-value interface called **`AsyncKV`**. Both persistence layers — history and step persistence — are implemented once against that interface, so a backend only has to provide four methods.

## The `AsyncKV` interface

A backend implements four async methods:

```python
class AsyncKV(Protocol):
    async def put(self, pk: str, sk: str, data: str) -> None: ...
    async def get(self, pk: str, sk: str) -> str | None: ...
    async def query(self, pk: str, sk_prefix: str | None = None) -> list[tuple[str, str]]: ...
    async def delete(self, pk: str, sk: str) -> None: ...
```

- `pk` / `sk` are a **partition key** and a **sort key** — the same two-key model DynamoDB, Cosmos, and Firestore all map onto cleanly.
- `query` returns `(sk, data)` pairs **ordered ascending by sort key**, optionally filtered by an `sk` prefix. Ordering is the one guarantee the stores rely on.
- `data` is always an opaque JSON string; serialization lives in the core, not the backend.

`InMemoryAsyncKV` is a built-in implementation for tests and local dev.

## History — `KVHistoryStore`

The simplest layer. PydanticAI hands you a full message list via `result.all_messages()`; you store it and load it back to resume a conversation.

```python
from pydantic_ai import Agent
from pydantic_ai_persistence import KVHistoryStore, InMemoryAsyncKV

agent = Agent("openai:gpt-4o")
store = KVHistoryStore(InMemoryAsyncKV())

result = agent.run_sync("Hi, I'm Kamal")
await store.save("conv-1", result.all_messages())

prior = await store.load("conv-1")                      # -> list[ModelMessage] | None
result = agent.run_sync("What's my name?", message_history=prior)
```

Messages are serialized with PydanticAI's own `ModelMessagesTypeAdapter`, so tool calls, structured parts, and multi-modal content round-trip exactly.

| Method | Description |
|---|---|
| `save(conversation_id, messages)` | Persist the full message list for a conversation (overwrites) |
| `load(conversation_id)` | Return the stored `list[ModelMessage]`, or `None` if absent |
| `delete(conversation_id)` | Remove a conversation's stored history |

## Step persistence — `KVStepStore`

`KVStepStore` implements PydanticAI's async **`StepStore`** protocol: the durable-execution layer that lets a run be paused, inspected, and resumed. Hand it to an agent as a capability:

```python
from pydantic_ai import Agent
from pydantic_ai_harness.step_persistence import StepPersistence
from pydantic_ai_persistence import KVStepStore, InMemoryAsyncKV

step_store = KVStepStore(InMemoryAsyncKV(), max_snapshots_per_run=10)
agent = Agent("openai:gpt-4o", capabilities=[StepPersistence(store=step_store)])
```

It records four kinds of durable state:

| Concern | What's stored |
|---|---|
| **Runs** | A `RunRecord` per run (conversation id, parent, agent name, start time), plus indexes for `list_runs` by conversation/parent. |
| **Events** | An append-only log of `StepEvent`s (one sort-key slot per sequence number). |
| **Snapshots** | `ContinuableSnapshot`s the run can resume from; `latest_snapshot` can include or exclude interrupted ones. |
| **Tool-effect ledger** | A `ToolEffectRecord` per `tool_call_id` so side-effecting tools aren't double-applied on resume. |

### Snapshot pruning

Snapshots are the heaviest records (they carry full message history). Pass `max_snapshots_per_run=N` to keep only the newest N per run — older snapshots are deleted as new ones are saved, while events and the tool ledger are untouched.

```python
KVStepStore(kv, max_snapshots_per_run=10)   # unbounded if omitted
```

## Key layout

For the curious, `KVStepStore` maps everything onto `AsyncKV` like this (per run):

| Record | `pk` | `sk` |
|---|---|---|
| Run metadata | `run#<run_id>` | `meta` |
| Event | `run#<run_id>` | `event#<zero-padded seq>` |
| Snapshot | `run#<run_id>` | `snap#<zero-padded seq>` |
| Tool effect | `run#<run_id>` | `tool#<tool_call_id>` |
| Run indexes | `runs#all` / `runs#conv#<cid>` / `runs#parent#<pid>` | `<started_at>#<run_id>` |

Zero-padding keeps the ascending `query` order numerically correct, which is why the `AsyncKV` ordering guarantee is all the stores need.

## Build your own backend

Implement the four `AsyncKV` methods for your datastore and hand the instance to `KVStepStore` / `KVHistoryStore` — no other code required. The [DynamoDB](dynamodb.md), [CosmosDB](cosmosdb.md), and [Firestore](firestore.md) providers are each a thin `AsyncKV` wrapper plus convenience subclasses; use any of them as a template.

!!! warning "Beta harness feature"
    `StepStore` lives in `pydantic-ai-harness` and is **beta/experimental** — its API may still change. `KVHistoryStore` does not depend on it and is stable.
