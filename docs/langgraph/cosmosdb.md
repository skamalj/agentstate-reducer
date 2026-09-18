# LangGraph Checkpointer — CosmosDB

A LangGraph `BaseCheckpointSaver` for **Azure CosmosDB** with **built-in message pruning**. It persists agent state between runs so your graphs can resume from any prior checkpoint, and it can automatically cap your message history before each write — no changes to your graph code or state annotations required.

!!! note "Current version"
    `langgraph-checkpoint-cosmosdb` **0.2.7** · Requires **Python 3.10+**

## What it is

`CosmosDBSaver` implements the LangGraph checkpointer interface (`put` / `get_tuple` / `list` plus async counterparts) backed by an Azure CosmosDB container. Unlike other CosmosDB checkpointers, it accepts an optional [`MessageReducer`](../reducer/index.md) that prunes the message list at the persistence layer.

- Full checkpoint persistence — save, retrieve, and list checkpoints
- Built-in message pruning at save time (see [Built-in message pruning](#built-in-message-pruning))
- Sync and async API
- Subgraph support — parent and subgraph state checkpointed independently
- Flexible auth — key-based or Azure RBAC
- Auto-creates the database and container under key-based auth

## Installation

=== "Base"

    ```bash
    pip install langgraph-checkpoint-cosmosdb
    ```

=== "With pruning"

    ```bash
    pip install "langgraph-checkpoint-cosmosdb[reducer]"
    ```

The `[reducer]` extra pulls in `agentstate-reducer`, required only if you pass a `reducer`.

## Database and container setup

| Auth mode | Database | Container | Partition key |
|---|---|---|---|
| **Key-based** (`COSMOSDB_KEY` set) | Created automatically if absent | Created automatically if absent | `/partition_key` (set by saver) |
| **RBAC / Managed Identity** (no key) | **Must pre-exist** | **Must pre-exist** | `/partition_key` (must be pre-configured) |

Key-based auth is the easiest way to get started — point the saver at an existing CosmosDB account and it provisions everything.

For RBAC, the saver only calls `get_database_client` / `get_container_client` (no setup-time write permissions), so the database and container must already exist:

```bash
az cosmosdb sql database create --account-name <account> --name <db>
az cosmosdb sql container create \
  --account-name <account> --database-name <db> --name <container> \
  --partition-key-path "/partition_key"
```

!!! warning "Partition key path"
    The partition key path **must** be `/partition_key` regardless of how the container is created.

## Authentication

=== "Key-based (dev)"

    ```bash
    export COSMOSDB_ENDPOINT="https://<account>.documents.azure.com:443/"
    export COSMOSDB_KEY="<your-key>"
    ```

=== "Azure RBAC (prod)"

    Set only the endpoint — no key. The saver uses `DefaultAzureCredential`, resolving in order: environment service principal → managed identity → `az login`.

    ```bash
    export COSMOSDB_ENDPOINT="https://<account>.documents.azure.com:443/"
    # COSMOSDB_KEY not set → DefaultAzureCredential is used
    ```

=== "User-assigned MI"

    ```bash
    export AZURE_CLIENT_ID="<managed-identity-client-id>"
    ```

=== "Service principal"

    ```bash
    export AZURE_TENANT_ID="<tenant-id>"
    export AZURE_CLIENT_ID="<client-id>"
    export AZURE_CLIENT_SECRET="<client-secret>"
    ```

## Quick start

```python
from langgraph.graph import StateGraph, MessagesState, START
from langchain_openai import ChatOpenAI
from langgraph_checkpoint_cosmosdb import CosmosDBSaver

model = ChatOpenAI(model="gpt-4o-mini")

def call_model(state: MessagesState):
    return {"messages": model.invoke(state["messages"])}

builder = StateGraph(MessagesState)
builder.add_node("call_model", call_model)
builder.add_edge(START, "call_model")

checkpointer = CosmosDBSaver(database_name="mydb", container_name="checkpoints")
graph = builder.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "user-123"}}

# First run — state is saved to CosmosDB
graph.invoke({"messages": [{"role": "user", "content": "Hi, I'm Kamal"}]}, config)

# Second run — picks up where it left off
graph.invoke({"messages": [{"role": "user", "content": "What's my name?"}]}, config)
```

## API reference

### `CosmosDBSaver(database_name, container_name, reducer=None, messages_key="messages")`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `database_name` | `str` | required | CosmosDB database name |
| `container_name` | `str` | required | CosmosDB container name |
| `reducer` | `MessageReducer` | `None` | Optional pruner — see [Built-in message pruning](#built-in-message-pruning) |
| `messages_key` | `str` | `"messages"` | State channel name that holds the message list |

### Sync methods

| Method | Description |
|---|---|
| `put(config, checkpoint, metadata, new_versions)` | Save a checkpoint |
| `put_writes(config, writes, task_id)` | Save pending writes for a checkpoint |
| `get_tuple(config)` | Retrieve the latest (or a specific) checkpoint |
| `list(config, *, before, limit)` | Iterate checkpoints for a thread |

### Async methods

All sync methods have async counterparts: `aput`, `aput_writes`, `aget_tuple`, `alist`, and `adelete`.

```python
checkpoint = await saver.aget_tuple(config)
await saver.adelete(thread_id="user-123", checkpoint_namespace="", checkpoint_id="<id>")
```

!!! note "`list` filtering"
    `list` only supports filtering by `thread_id`. The `filter` parameter (filtering by metadata) is not yet implemented.

## Built-in message pruning

Long-running agents accumulate message history with every turn, inflating checkpoint size, increasing storage costs, and eventually blowing past LLM context limits.

Pass a [`MessageReducer`](../reducer/index.md) and the saver prunes the message list inside `put()` before the checkpoint is serialised and written to CosmosDB. **Your graph code, state definition, and node logic stay untouched.** This is an alternative to — or complement of — the LangGraph `Annotated[list, reducer_fn]` pattern; use it when:

- You don't own the graph or state definition (e.g. a pre-built LangGraph agent)
- You want pruning at every save, regardless of which node triggered it
- You want in-memory state intact and only prune what gets persisted

```python
from agentstate_reducer import MessageReducer
from langgraph_checkpoint_cosmosdb import CosmosDBSaver

reducer = MessageReducer(min_messages=10, max_messages=20)

checkpointer = CosmosDBSaver(
    database_name="mydb",
    container_name="checkpoints",
    reducer=reducer,        # prune before each checkpoint save
    messages_key="messages" # state channel holding the message list (default)
)
```

When `len(messages) > max_messages`, the oldest `human`/`ai` messages are removed until `min_messages` remain. System-prompt index 0, `system`/`function` messages, and `tool` messages (unless their parent `ai` message is pruned) are preserved.

!!! tip "Full reducer configuration"
    For `preserve_first`, `cascade_tool_messages`, `summarize_fn`, token budgeting, and role aliases, see the [reducer overview](../reducer/index.md) and [token budget](../reducer/token-budget.md) docs.

## Long-term memory via `on_prune`

!!! success "New in langgraph-checkpoint-cosmosdb 0.3.1"
    Messages pruned from the checkpoint are exactly the ones leaving the model's view. The saver forwards a **memory namespace** to the reducer, and any [`on_prune`](../reducer/long-term-memory.md) hook receives `(pruned_messages, namespace)` — so pruned turns flow straight into a LangGraph `BaseStore`, LangMem, or any memory engine, with no extra node and no package coupling.

```python
from uuid import uuid4
from agentstate_reducer import MessageReducer, ReducerConfig, Background
from langgraph_checkpoint_cosmosdb import CosmosDBSaver

store = ...  # any langgraph BaseStore

def remember(pruned, namespace):
    for m in pruned:
        store.put(tuple(namespace), key=str(uuid4()), value={"role": m.type, "content": m.content})

reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[remember]))
# on_prune=[Background(remember)] runs a slow hook (e.g. LLM extraction) off the request path
saver = CosmosDBSaver(database_name="mydb", container_name="checkpoints", reducer=reducer)
graph = builder.compile(checkpointer=saver, store=store)

graph.invoke(input, config={"configurable": {
    "thread_id": uuid4().hex,                    # short-term scope (this checkpoint)
    "memory_namespace": ("memories", user_id),   # long-term scope (the store)
}})
```

The saver reads `memory_namespace` (or whatever `ReducerConfig.namespace_key` names) from `config["configurable"]` on every `put()` and passes it through untouched. If the app never sets it, the namespace falls back to `("memories", thread_id)`. Each pruned message reaches the hooks **once**, even though LangGraph writes several checkpoints per turn. Requires `agentstate-reducer>=0.4.0`.

## Data model

Checkpoints and writes are stored as separate items in the same container, differentiated by a key prefix and partition key:

| Item type | Partition key format | Item id format |
|---|---|---|
| Checkpoint | `checkpoint$<thread_id>$<ns>$` | `checkpoint$<thread_id>$<ns>$<checkpoint_id>` |
| Pending write | `writes$<thread_id>$<ns>$<checkpoint_id>$` | `writes$<thread_id>$<ns>$<checkpoint_id>$<task_id>$<idx>` |

The container requires a partition key path of `/partition_key`.
