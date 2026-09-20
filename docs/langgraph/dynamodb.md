# LangGraph Checkpointer — DynamoDB

A LangGraph `BaseCheckpointSaver` for **Amazon DynamoDB** with **built-in message pruning**. It persists agent state between runs so your graphs can resume from any prior checkpoint, and it can automatically cap your message history before each write — no changes to your graph code or state annotations required.

!!! note "Current version"
    `langgraph-dynamodb-checkpoint` **0.3.1** · Requires **Python 3.10+**

## What it is

`DynamoDBSaver` implements the LangGraph checkpointer interface (`put` / `get_tuple` / `list` plus async counterparts) backed by a single Amazon DynamoDB table. Unlike other DynamoDB checkpointers, it accepts an optional [`MessageReducer`](../reducer/index.md) that prunes the message list at the persistence layer.

- Full checkpoint persistence — save, retrieve, and list checkpoints
- Built-in message pruning at save time (see [Built-in message pruning](#built-in-message-pruning))
- Sync and async API
- Single-table design — checkpoints and pending writes share one table
- Auto-creates the table (on-demand billing) on first use if it doesn't exist
- Optional TTL-based expiry and delete-by-`thread_id`

## Installation

=== "Base"

    ```bash
    pip install langgraph_dynamodb_checkpoint
    ```

=== "With pruning"

    ```bash
    pip install "langgraph_dynamodb_checkpoint[reducer]"
    ```

The `[reducer]` extra pulls in `agentstate-reducer`, required only if you pass a `reducer`.

## Authentication

The saver creates a boto3 resource with `boto3.resource('dynamodb')`, so it uses the **standard AWS credential and region resolution chain** — no credentials or region are passed to the constructor. Configure them the usual way:

=== "Environment variables"

    ```bash
    export AWS_ACCESS_KEY_ID="<access-key>"
    export AWS_SECRET_ACCESS_KEY="<secret-key>"
    export AWS_DEFAULT_REGION="us-east-1"
    ```

=== "Shared profile"

    ```bash
    export AWS_PROFILE="my-profile"
    export AWS_DEFAULT_REGION="us-east-1"
    ```

    Credentials are read from `~/.aws/credentials` and `~/.aws/config`.

=== "IAM role"

    When running on AWS (EC2, ECS, Lambda, EKS), no keys are needed — the
    attached IAM role is resolved automatically from the instance/task
    metadata.

=== "Local DynamoDB"

    Point the AWS SDK at a local DynamoDB endpoint via the standard
    endpoint environment variable (boto3 ≥ 1.28):

    ```bash
    export AWS_ENDPOINT_URL_DYNAMODB="http://localhost:8000"
    export AWS_DEFAULT_REGION="us-east-1"
    export AWS_ACCESS_KEY_ID="dummy"
    export AWS_SECRET_ACCESS_KEY="dummy"
    ```

!!! warning "Required IAM permissions"
    The credentials must allow reading and writing table items, plus
    `CreateTable` / `DescribeTable` / `UpdateTimeToLive` if you want the saver
    to auto-create the table on first use.

## Quick start

```python
from langgraph.graph import StateGraph, MessagesState, START
from langchain_openai import ChatOpenAI
from langgraph_dynamodb_checkpoint import DynamoDBSaver

model = ChatOpenAI(model="gpt-4o-mini")

def call_model(state: MessagesState):
    return {"messages": model.invoke(state["messages"])}

builder = StateGraph(MessagesState)
builder.add_node("call_model", call_model)
builder.add_edge(START, "call_model")

checkpointer = DynamoDBSaver(table_name="langgraph-checkpoints")
graph = builder.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "user-123"}}

# First run — state is saved to DynamoDB
graph.invoke({"messages": [{"role": "user", "content": "Hi, I'm Kamal"}]}, config)

# Second run — picks up where it left off
graph.invoke({"messages": [{"role": "user", "content": "What's my name?"}]}, config)
```

The table is created automatically on first use if it doesn't already exist.

### With the reducer enabled

Pass a [`MessageReducer`](../reducer/index.md) to cap the message history before every checkpoint write:

```python
from agentstate_reducer import MessageReducer
from langgraph_dynamodb_checkpoint import DynamoDBSaver

reducer = MessageReducer(min_messages=10, max_messages=20)

checkpointer = DynamoDBSaver(
    table_name="langgraph-checkpoints",
    reducer=reducer,          # prune before each checkpoint save
    messages_key="messages",  # state channel holding the message list (default)
)
graph = builder.compile(checkpointer=checkpointer)
```

### Context-manager initialization

`from_conn_info` is a convenience factory that accepts the same arguments:

```python
from langgraph_dynamodb_checkpoint import DynamoDBSaver

with DynamoDBSaver.from_conn_info(table_name="langgraph-checkpoints") as saver:
    graph = builder.compile(checkpointer=saver)
    graph.invoke({"messages": [{"role": "user", "content": "Hello"}]}, config)
```

## API reference

### `DynamoDBSaver(table_name, max_read_request_units=100, max_write_request_units=100, ttl_seconds=None, reducer=None, messages_key="messages")`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `table_name` | `str` | required | DynamoDB table name (created if absent) |
| `max_read_request_units` | `int` | `100` | On-demand max read request units set when the table is created |
| `max_write_request_units` | `int` | `100` | On-demand max write request units set when the table is created |
| `ttl_seconds` | `int` | `None` | If set, each item gets a `ttl` attribute `now + ttl_seconds`; TTL is enabled on the table at creation |
| `reducer` | `MessageReducer` | `None` | Optional pruner — see [Built-in message pruning](#built-in-message-pruning) |
| `messages_key` | `str` | `"messages"` | State channel name that holds the message list |

!!! note "AWS session"
    Region, credentials, and (for local DynamoDB) endpoint are taken from the
    default boto3 session — they are **not** constructor arguments. See
    [Authentication](#authentication).

The context-manager factory `DynamoDBSaver.from_conn_info(*, table_name, max_read_request_units=100, max_write_request_units=100, ttl_seconds=None, reducer=None, messages_key="messages")` accepts the same arguments.

### Sync methods

| Method | Description |
|---|---|
| `put(config, checkpoint, metadata, new_versions)` | Save a checkpoint (applies the reducer first) |
| `put_writes(config, writes, task_id)` | Save pending writes for a checkpoint |
| `get_tuple(config)` | Retrieve the latest (or a specific) checkpoint |
| `list(config, *, filter, before, limit)` | Iterate checkpoints for a thread, newest first |
| `delete(config)` | Delete **all** items for the config's `thread_id` |

### Async methods

The core methods have async counterparts backed by an executor: `aput`, `aput_writes`, `aget`, `aget_tuple`, and `alist`.

```python
checkpoint = await saver.aget_tuple(config)
async for tup in saver.alist(config, limit=10):
    ...
```

!!! note "`list` filtering"
    `list` accepts `filter`, `before`, and `limit`. `before` and `limit` are
    honoured; the `filter` (metadata) parameter is accepted but not applied.

## Built-in message pruning

Long-running agents accumulate message history with every turn, inflating checkpoint size, increasing DynamoDB storage/throughput cost, and eventually blowing past LLM context limits.

Pass a [`MessageReducer`](../reducer/index.md) and the saver prunes the message list inside `put()` — via its internal `_apply_reducer` step — before the checkpoint is serialised and written to DynamoDB. **Your graph code, state definition, and node logic stay untouched.** This is an alternative to — or complement of — the LangGraph `Annotated[list, reducer_fn]` pattern; use it when:

- You don't own the graph or state definition (e.g. a pre-built LangGraph agent)
- You want pruning at every save, regardless of which node triggered it
- You want in-memory state intact and only prune what gets persisted

```python
from agentstate_reducer import MessageReducer
from langgraph_dynamodb_checkpoint import DynamoDBSaver

reducer = MessageReducer(min_messages=10, max_messages=20)

checkpointer = DynamoDBSaver(
    table_name="langgraph-checkpoints",
    reducer=reducer,        # prune before each checkpoint save
    messages_key="messages" # state channel holding the message list (default)
)
```

For **token-budget** pruning, drive the reducer with a `ReducerConfig` instead — prune whole messages only, never truncated:

```python
from agentstate_reducer import MessageReducer, ReducerConfig
from langgraph_dynamodb_checkpoint import DynamoDBSaver

reducer = MessageReducer(config=ReducerConfig(max_tokens=4000, target_tokens=2000))
checkpointer = DynamoDBSaver(table_name="langgraph-checkpoints", reducer=reducer)
```

When pruning triggers, the oldest `human`/`ai` messages are removed until the target is met. Index 0 (typically the system prompt), `system`/`function` messages, and `tool` messages (unless their parent `ai` message is pruned) are preserved.

!!! tip "Full reducer configuration"
    For `preserve_first`, `cascade_tool_messages`, `summarize_fn`, token budgeting, and role aliases, see the [reducer overview](../reducer/index.md) and [token budget](../reducer/token-budget.md) docs.

## Long-term memory via `on_prune`

!!! success "New in langgraph-dynamodb-checkpoint 0.4.0"
    Messages pruned from the checkpoint are exactly the ones leaving the model's view. The saver forwards a **memory namespace** to the reducer, and any [`on_prune`](../reducer/long-term-memory.md) hook receives `(pruned_messages, namespace)` — so pruned turns flow straight into a LangGraph `BaseStore`, LangMem, or any memory engine, with no extra node and no package coupling.

```python
from uuid import uuid4
from agentstate_reducer import MessageReducer, ReducerConfig, Background
from langgraph_dynamodb_checkpoint import DynamoDBSaver

store = ...  # any langgraph BaseStore

def remember(pruned, namespace):
    for m in pruned:
        store.put(tuple(namespace), key=str(uuid4()), value={"role": m.type, "content": m.content})

reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[remember]))
# on_prune=[Background(remember)] runs a slow hook (e.g. LLM extraction) off the request path
saver = DynamoDBSaver(table_name="langgraph-checkpoints", reducer=reducer)
graph = builder.compile(checkpointer=saver, store=store)

graph.invoke(input, config={"configurable": {
    "thread_id": uuid4().hex,                    # short-term scope (this checkpoint)
    "memory_namespace": ("memories", user_id),   # long-term scope (the store)
}})
```

The saver reads `memory_namespace` (or whatever `ReducerConfig.namespace_key` names) from `config["configurable"]` on every `put()` and passes it through untouched. If the app never sets it, the namespace falls back to `("memories", thread_id)`. Each pruned message reaches the hooks **once**, even though LangGraph writes several checkpoints per turn. Requires `agentstate-reducer>=0.4.0`.

## Conformance

!!! success "Passes LangGraph's official checkpointer conformance suite — FULL base (langgraph-dynamodb-checkpoint 0.4.1)"
    Validated with [`langgraph-checkpoint-conformance`](https://pypi.org/project/langgraph-checkpoint-conformance/), the suite LangGraph's docs name as the validation path: `put`, `put_writes`, `get_tuple`, `list` (ordering, `before`, `limit`, metadata filters, namespaces, pending writes) and `delete_thread` all pass. The extended capabilities `copy_thread`, `delete_for_runs` and `prune` are not implemented. 0.4.1 also raised the floor to `langgraph-checkpoint>=4.1.1`, which carries the serde security fixes, and fixed a pending-writes bug where several writes from one task overwrote each other. The conformance test ships in the repo's `tests/`.

## Data model

The saver uses a **single-table design** with a composite primary key. Checkpoints and pending writes are stored as separate items in the same table, distinguished by their sort key and a `checkpoint_key` attribute.

| Key | Attribute | Type | Description |
|---|---|---|---|
| Partition key (HASH) | `PK` | `String` | `thread_id` |
| Sort key (RANGE) | `SK` | `String` | `checkpoint_id` for checkpoints; `<checkpoint_id>$<task_id>` for pending writes |

Each item also carries a `checkpoint_key` attribute used for prefix filtering:

| Item type | `checkpoint_key` format |
|---|---|
| Checkpoint | `checkpoint$<thread_id>$<ns>$<checkpoint_id>` |
| Pending write | `writes$<thread_id>$<ns>$<checkpoint_id>$<task_id>$<idx>` |

When `ttl_seconds` is set, items also carry a numeric `ttl` attribute (epoch seconds), and DynamoDB TTL is enabled on the `ttl` attribute at table creation. The table is created with `PAY_PER_REQUEST` (on-demand) billing.
