# CrewAI Persistence — DynamoDB

A CrewAI `FlowPersistence` backend for **Amazon DynamoDB** with **built-in message pruning**. It persists flow state between steps so your flows can resume from any saved checkpoint, and it can automatically cap your message history before each write — no changes to your flow code or state model required.

!!! note "Current version"
    `crewai-persistence-dynamodb` **0.1.0** · Requires **Python >=3.10,<3.14** (CrewAI constraint) and **crewai>=1.0.0**

## What it is

`DynamoDBFlowPersistence` subclasses `crewai.flow.persistence.base.FlowPersistence` (a Pydantic `BaseModel` + ABC in CrewAI 1.x) and stores CrewAI flow state in a DynamoDB table. Configuration (`table_name`, `region_name`, `endpoint_url`, `ttl_seconds`, `messages_key`) is declared as Pydantic fields, while the runtime objects (the boto3 session/clients and the reducer) are held as `PrivateAttr`. It accepts an optional [`MessageReducer`](../reducer/index.md) that prunes the message list at the persistence layer.

Persistence is keyed by the flow state's `id` field — the `flow_uuid`. One item is stored per flow run: each save upserts the latest state via `put_item`, so `load_state` returns the most recent. Flow state is serialised to a JSON string in a `data` attribute (which sidesteps DynamoDB's float/Decimal and empty-value quirks). `save_state` accepts either a Pydantic `BaseModel` or a plain dict; `load_state` returns a dict (or `None`).

## Installation

=== "Base"

    ```bash
    pip install crewai-persistence-dynamodb
    ```

=== "With pruning"

    ```bash
    pip install "crewai-persistence-dynamodb[reducer]"
    ```

The `[reducer]` extra pulls in `agentstate-reducer`, required only if you pass a `reducer`.

## Table setup

| Behaviour | Detail |
|---|---|
| **Table creation** | Created automatically if absent, with `PAY_PER_REQUEST` billing |
| **Key schema** | Partition (HASH) key `flow_uuid` of type `S` (string) |
| **TTL** | If `ttl_seconds` is set, TTL is enabled on the `ttl` attribute at creation time |

The backend calls `init_db()` from `__init__`: it tries to `load()` the table, and if it does not exist (`ResourceNotFoundException`), creates it and waits until it is active.

!!! warning "IAM permissions"
    Auto-creation needs `dynamodb:CreateTable`, `dynamodb:DescribeTable`, and (for TTL) `dynamodb:UpdateTimeToLive`. If the table is pre-provisioned, `dynamodb:GetItem` and `dynamodb:PutItem` are sufficient.

## Authentication

DynamoDB uses the standard AWS credential chain via boto3. Provide credentials through the environment, a shared profile, or an explicit `boto_session`.

=== "Environment / profile (dev)"

    ```bash
    export AWS_ACCESS_KEY_ID="<key>"
    export AWS_SECRET_ACCESS_KEY="<secret>"
    export AWS_DEFAULT_REGION="us-east-1"
    ```

=== "IAM role (prod)"

    Omit static keys. On EC2/ECS/Lambda the attached IAM role is resolved automatically by boto3's default credential chain.

=== "Local DynamoDB"

    Point `endpoint_url` at a local instance (e.g. DynamoDB Local):

    ```bash
    export AWS_ACCESS_KEY_ID="dummy"
    export AWS_SECRET_ACCESS_KEY="dummy"
    # endpoint_url="http://localhost:8000" passed to the constructor
    ```

## Quick start

### Normal flow

```python
from crewai.flow.flow import Flow, start, listen
from crewai.flow.persistence import persist
from crewai_persistence_dynamodb import DynamoDBFlowPersistence

persistence = DynamoDBFlowPersistence(
    table_name="crewai_flow_states",
    region_name="us-east-1",
)

@persist(persistence)
class MyFlow(Flow):
    @start()
    def first_step(self):
        return {"status": "started", "value": 42}

    @listen(first_step)
    def second_step(self, data):
        return data

flow = MyFlow()
flow.kickoff()
```

### Conversational flow (with message history and pruning)

```python
from crewai.flow.flow import Flow, start, listen
from crewai.flow.persistence import persist
from agentstate_reducer import MessageReducer
from agentstate_reducer.models import ReducerConfig
from crewai_persistence_dynamodb import DynamoDBFlowPersistence

reducer = MessageReducer(config=ReducerConfig(min_messages=10, max_messages=20))

persistence = DynamoDBFlowPersistence(
    table_name="crewai_flow_states",
    region_name="us-east-1",
    reducer=reducer,         # prune before each save
    messages_key="messages", # state key holding the message list (default)
)

@persist(persistence)
class ChatFlow(Flow):
    @start()
    def handle_turn(self):
        # messages accumulate here; pruning happens automatically at save time
        messages = self.state.get("messages", [])
        messages.append({"role": "human", "content": "Tell me about DynamoDB."})
        # ... call your LLM here ...
        messages.append({"role": "ai", "content": "DynamoDB is a managed NoSQL key-value store..."})
        return {"messages": messages}

flow = ChatFlow()
flow.kickoff()
```

!!! note "The `@persist` decorator"
    `@persist` is imported from `crewai.flow.persistence`. Applied to a `Flow` subclass with your persistence instance, it transparently calls `save_state` / `load_state` keyed by the flow state's `id` (the `flow_uuid`).

## API reference

### `DynamoDBFlowPersistence(table_name, *, region_name=None, boto_session=None, endpoint_url=None, ttl_seconds=None, reducer=None, messages_key="messages")`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `table_name` | `str` | required | DynamoDB table name (created if absent) |
| `region_name` | `str \| None` | `None` | AWS region for the boto3 session |
| `boto_session` | `boto3.Session \| None` | `None` | Pre-configured boto3 session; if omitted, one is built from `region_name` |
| `endpoint_url` | `str \| None` | `None` | Custom endpoint (e.g. DynamoDB Local) |
| `ttl_seconds` | `int \| None` | `None` | If set, items expire after this many seconds (TTL enabled on the `ttl` attribute) |
| `reducer` | `MessageReducer \| None` | `None` | Optional pruner — see [Built-in message pruning](#built-in-message-pruning) |
| `messages_key` | `str` | `"messages"` | State key that holds the message list |

### Methods

| Method | Description |
|---|---|
| `init_db()` | Create the boto3 clients and ensure the table exists (called automatically by `__init__`) |
| `save_state(flow_uuid, method_name, state_data)` | Persist flow state (upsert by `flow_uuid` via `put_item`); accepts a `BaseModel` or dict |
| `load_state(flow_uuid)` | Load the most recently saved state as a dict (consistent read); returns `None` if not found |

## Built-in message pruning

Long-running conversational flows accumulate message history with every turn, inflating item size, increasing DynamoDB storage/throughput costs, and eventually blowing past LLM context limits.

Pass a [`MessageReducer`](../reducer/index.md) and the backend prunes the message list inside `save_state()` before the item is written to DynamoDB. **Your flow code and state model stay untouched.**

When `len(messages) > max_messages`, the oldest `human`/`ai` messages are removed until `min_messages` remain. System-prompt index 0, `system`/`function` messages, and `tool` messages (unless their parent `ai` message is pruned) are preserved.

!!! tip "Full reducer configuration"
    For `preserve_first`, `cascade_tool_messages`, `summarize_fn`, token budgeting, and role aliases, see the [reducer overview](../reducer/index.md) and [token budget](../reducer/token-budget.md) docs.

## Long-term memory via `on_prune`

!!! success "New in crewai-persistence-dynamodb 0.2.0"
    Messages pruned from the flow state are exactly the ones leaving the model's view. The persistence layer forwards a **memory namespace** to the reducer, and any [`on_prune`](../reducer/long-term-memory.md) hook receives `(pruned_messages, namespace)` — so pruned turns can flow straight into CrewAI's unified `Memory` on a [cloud backend](memory.md), with no package coupling.

```python
from agentstate_reducer import MessageReducer, ReducerConfig, Background
from crewai.memory import Memory

memory = Memory(storage=...)                     # e.g. crewai-memory-dynamodb

def remember(pruned, namespace):
    text = "
".join(m["content"] for m in pruned)
    memory.remember_many(memory.extract_memories(text), scope=namespace)   # LLM calls -> off the request path

reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))

class SupportState(BaseModel):
    id: str = ""
    memory_namespace: str = "/user/kamal"        # long-term scope: the USER, not the flow
    messages: list = []

@persist(DynamoDBFlowPersistence(..., reducer=reducer))
class SupportFlow(Flow[SupportState]):
    ...
```

The persistence layer reads `memory_namespace` (or whatever `ReducerConfig.namespace_key` names) from the flow state on every `save_state` and passes it through untouched. If the state never sets it, the namespace falls back to `"/flow/<flow_uuid>"`. Each pruned message reaches the hooks once. Requires `agentstate-reducer>=0.4.0`.

## Data model

Each call to `save_state` upserts a single DynamoDB item keyed by `flow_uuid`. Only the latest state for each flow run is stored (`put_item` overwrites on the same key).

| Attribute | Description |
|---|---|
| `flow_uuid` | Unique identifier for the flow run (partition key) |
| `data` | The full state dict serialised as a JSON string |
| `method_name` | Name of the flow method that triggered the save |
| `saved_at` | ISO-8601 UTC timestamp of the save |
| `ttl` | (Only when `ttl_seconds` is set) Unix epoch expiry time |

!!! note "JSON serialisation"
    State is stored as a JSON string rather than native DynamoDB attributes, avoiding DynamoDB's float/`Decimal` conversion and empty-string/empty-set restrictions. `load_state` parses `data` back into a dict.
