# LangGraph Checkpointer — Firestore

A LangGraph `BaseCheckpointSaver` for **Google Firestore** with **built-in message pruning**. It persists agent state between runs so your graphs can resume from any prior checkpoint, and it can automatically cap your message history before each write — no changes to your graph code or state annotations required.

!!! note "Current version"
    `langgraph-checkpoint-firestore` **0.2.1** · Requires **Python 3.10+**

## What it is

`FirestoreSaver` implements the LangGraph checkpointer interface (`put` / `get_tuple` / `list` plus async counterparts) backed by Google Firestore. Unlike other Firestore checkpointers, it accepts an optional [`MessageReducer`](../reducer/index.md) that prunes the message list at the persistence layer.

- Full checkpoint persistence — save, retrieve, and list checkpoints
- Built-in message pruning at save time (see [Built-in message pruning](#built-in-message-pruning))
- Sync and async API
- Subgraph support — parent and subgraph state checkpointed independently
- Native Firestore hierarchy — checkpoints in per-thread subcollections for efficient queries

## Installation

=== "Base"

    ```bash
    pip install langgraph-checkpoint-firestore
    ```

=== "With pruning"

    ```bash
    pip install "langgraph-checkpoint-firestore[reducer]"
    ```

The `[reducer]` extra pulls in `agentstate-reducer`, required only if you pass a `reducer`.

## Firestore setup

The saver uses Google Cloud Application Default Credentials (ADC).

=== "Local development"

    ```bash
    gcloud auth application-default login
    ```

=== "Service account (CI / prod)"

    ```bash
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
    ```

!!! warning "Native mode required"
    Your Firestore instance must be in **Native mode** (not Datastore mode). Collections are created automatically on first write — no manual schema setup required.

## Quick start

The recommended entry point is the `from_conn_info` context manager:

```python
from langgraph.graph import StateGraph, MessagesState, START
from langchain_openai import ChatOpenAI
from langgraph_checkpoint_firestore import FirestoreSaver

model = ChatOpenAI(model="gpt-4o-mini")

def call_model(state: MessagesState):
    return {"messages": model.invoke(state["messages"])}

builder = StateGraph(MessagesState)
builder.add_node("call_model", call_model)
builder.add_edge(START, "call_model")

with FirestoreSaver.from_conn_info(
    project_id="my-gcp-project",
    checkpoints_collection="checkpoints",
) as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "user-123"}}

    # First run — state is saved to Firestore
    graph.invoke({"messages": [{"role": "user", "content": "Hi, I'm Kamal"}]}, config)

    # Second run — picks up where it left off
    graph.invoke({"messages": [{"role": "user", "content": "What's my name?"}]}, config)
```

## API reference

### `FirestoreSaver(project_id, checkpoints_collection, reducer=None, messages_key="messages")`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_id` | `str` | required | Google Cloud project ID |
| `checkpoints_collection` | `str` | `"checkpoints"` | Root Firestore collection name |
| `reducer` | `MessageReducer` | `None` | Optional pruner — see [Built-in message pruning](#built-in-message-pruning) |
| `messages_key` | `str` | `"messages"` | State channel name that holds the message list |

The context-manager factory accepts the same arguments:

```python
with FirestoreSaver.from_conn_info(
    project_id="my-gcp-project",
    checkpoints_collection="checkpoints",
    reducer=reducer,
    messages_key="messages",
) as saver:
    graph = builder.compile(checkpointer=saver)
```

### Sync methods

| Method | Description |
|---|---|
| `put(config, checkpoint, metadata, new_versions)` | Save a checkpoint |
| `put_writes(config, writes, task_id)` | Save pending writes for a checkpoint |
| `get_tuple(config)` | Retrieve the latest (or a specific) checkpoint |
| `list(config, *, before, limit)` | Iterate checkpoints for a thread |

### Async methods

All sync methods have async counterparts: `aput`, `aput_writes`, `aget_tuple`, `alist`.

## Built-in message pruning

Long-running agents accumulate message history with every turn, inflating checkpoint size, increasing Firestore storage costs, and eventually blowing past LLM context limits.

Pass a [`MessageReducer`](../reducer/index.md) and the saver prunes the message list inside `put()` before the checkpoint is serialised and written to Firestore. **Your graph code, state definition, and node logic stay untouched.** This is an alternative to — or complement of — the LangGraph `Annotated[list, reducer_fn]` pattern; use it when:

- You don't own the graph or state definition (e.g. a pre-built LangGraph agent)
- You want pruning at every save, regardless of which node triggered it
- You want in-memory state intact and only prune what gets persisted

```python
from agentstate_reducer import MessageReducer
from langgraph_checkpoint_firestore import FirestoreSaver

reducer = MessageReducer(min_messages=10, max_messages=20)

with FirestoreSaver.from_conn_info(
    project_id="my-gcp-project",
    checkpoints_collection="checkpoints",
    reducer=reducer,        # prune before each checkpoint save
    messages_key="messages" # state channel holding the message list (default)
) as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)
```

When `len(messages) > max_messages`, the oldest `human`/`ai` messages are removed until `min_messages` remain. System-prompt index 0, `system`/`function` messages, and `tool` messages (unless their parent `ai` message is pruned) are preserved.

!!! tip "Full reducer configuration"
    For `preserve_first`, `cascade_tool_messages`, `summarize_fn`, token budgeting, and role aliases, see the [reducer overview](../reducer/index.md) and [token budget](../reducer/token-budget.md) docs.

## Long-term memory via `on_prune`

!!! success "New in langgraph-checkpoint-firestore 0.3.0"
    Messages pruned from the checkpoint are exactly the ones leaving the model's view. The saver forwards a **memory namespace** to the reducer, and any [`on_prune`](../reducer/long-term-memory.md) hook receives `(pruned_messages, namespace)` — so pruned turns flow straight into a LangGraph `BaseStore`, LangMem, or any memory engine, with no extra node and no package coupling.

```python
from uuid import uuid4
from agentstate_reducer import MessageReducer, ReducerConfig, Background
from langgraph_checkpoint_firestore import FirestoreSaver

store = ...  # any langgraph BaseStore

def remember(pruned, namespace):
    for m in pruned:
        store.put(tuple(namespace), key=str(uuid4()), value={"role": m.type, "content": m.content})

reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[remember]))
# on_prune=[Background(remember)] runs a slow hook (e.g. LLM extraction) off the request path
saver = FirestoreSaver("my-project", "checkpoints", reducer=reducer)
graph = builder.compile(checkpointer=saver, store=store)

graph.invoke(input, config={"configurable": {
    "thread_id": uuid4().hex,                    # short-term scope (this checkpoint)
    "memory_namespace": ("memories", user_id),   # long-term scope (the store)
}})
```

The saver reads `memory_namespace` (or whatever `ReducerConfig.namespace_key` names) from `config["configurable"]` on every `put()` and passes it through untouched. If the app never sets it, the namespace falls back to `("memories", thread_id)`. Each pruned message reaches the hooks **once**, even though LangGraph writes several checkpoints per turn. Requires `agentstate-reducer>=0.4.0`.

## Conformance

!!! success "Passes LangGraph's official checkpointer conformance suite — FULL base (langgraph-checkpoint-firestore 0.3.1)"
    Validated with [`langgraph-checkpoint-conformance`](https://pypi.org/project/langgraph-checkpoint-conformance/), the suite LangGraph's docs name as the validation path: `put`, `put_writes`, `get_tuple`, `list` (ordering, `before`, `limit`, metadata filters, namespaces, pending writes) and `delete_thread` all pass. The extended capabilities `copy_thread`, `delete_for_runs` and `prune` are not implemented. 0.3.1 also raised the floor to `langgraph-checkpoint>=4.1.1`, which carries the serde security fixes, and fixed a pending-writes bug where several writes from one task overwrote each other. The conformance test ships in the repo's `tests/`.

## Data model

Checkpoints are stored in a hierarchical Firestore structure, co-locating each checkpoint with its pending writes and enabling efficient per-thread queries:

```
{checkpoints_collection}/
  {thread_id}_{checkpoint_ns}/          ← partition document
    checkpoints/
      {checkpoint_id}                   ← checkpoint document
        writes/
          {task_id}_{idx}               ← pending write documents
```
