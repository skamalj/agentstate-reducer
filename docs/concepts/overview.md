# State Management Overview

AI agents carry **state** between steps and runs. For conversational agents, the bulk of that state is the **message history**. Two concerns dominate:

1. **Pruning** — keeping the history small enough to stay fast, cheap, and within context limits.
2. **Persistence** — storing state durably so an agent can resume later.

This toolkit treats them as separate, composable concerns.

## Pruning

Pruning decides *which messages to keep* when history grows too large. There are two strategies, both supported by [agentstate-reducer](../reducer/index.md):

- **Message-count pruning** — keep at most N messages. Simple and predictable.
- **Token-budget pruning** — keep messages until a token budget is hit. Maps directly to model context limits and cost.

In both cases, the reducer drops **whole messages** — it never truncates content, so you never send a model a half-cut message. It also preserves the system prompt and keeps tool-call/tool-result pairs consistent.

### Where pruning runs

| Location | How | When to use |
|---|---|---|
| **In the graph/state** | LangGraph `Annotated[list, reducer_fn]` | You own the state definition and want pruning on every state merge |
| **At the persistence layer** | `reducer=` param on a checkpoint/persistence backend | You *don't* own the state, or want pruning only on what gets stored |

The second approach is the key idea behind the integrations here: pruning happens transparently inside `put()`/`save_state()` right before serialization — **your graph and node code stay untouched**.

## Persistence

Persistence stores state keyed by a thread/flow identifier so it can be reloaded. The integrations cover two clouds and two frameworks:

|  | Azure CosmosDB | Google Firestore |
|---|---|---|
| **LangGraph** | `langgraph-checkpoint-cosmosdb` | `langgraph-checkpoint-firestore` |
| **CrewAI** | `crewai-persistence-cosmosdb` | `crewai-persistence-firestore` |

### LangGraph vs CrewAI persistence

They solve the same problem but with different framework contracts:

| | LangGraph | CrewAI Flows |
|---|---|---|
| Interface | `BaseCheckpointSaver` (`put`/`get_tuple`/`list`) | `FlowPersistence` (`save_state`/`load_state`/`init_db`) |
| Trigger | Framework calls `put()` after each step | `@persist` decorator calls `save_state()` after decorated methods |
| State shape | LangGraph `Checkpoint` dict (channels) | Pydantic `BaseModel` or dict |
| Resume granularity | Per-node (mid-graph) | Per flow run (from last saved state) |
| Keyed by | `thread_id` + checkpoint namespace | `flow_uuid` (the flow state's `id`) |

## Combining the two

Every persistence integration accepts an optional `reducer`. When set, it prunes the message list *before* writing:

```python
reducer = MessageReducer(max_tokens=4000, target_tokens=2000)
# pruning now happens automatically inside every save — no graph changes
```

This is the recommended pattern for production conversational agents: **persist for durability, prune for efficiency, in one place**.

## From pruning to long-term memory

Short-term state (the checkpoint) and long-term memory (a store) are separate pipes; nothing built-in moves history from one to the other. Because the reducer already computes *which messages are leaving the window*, it is the natural junction: **[`on_prune` hooks](../reducer/long-term-memory.md)** hand that slice to any callable, and the persistence integration forwards the app's **memory namespace** (the user, not the thread) so the two scopes never mix.

```python
reducer = MessageReducer(config=ReducerConfig(max_tokens=4000, on_prune=[remember]))
# every prune now also writes to long-term memory — exactly once per message
```
