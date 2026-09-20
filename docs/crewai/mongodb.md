# CrewAI Persistence — MongoDB

A CrewAI `FlowPersistence` backend for **MongoDB** with **built-in message pruning**. It persists flow state between steps so your flows can resume from any saved checkpoint, and it can automatically cap your message history before each write — no changes to your flow code or state model required.

!!! note "Current version"
    `crewai-persistence-mongodb` **0.1.0** · Requires **Python >=3.10,<3.14** (CrewAI constraint) and **crewai>=1.0.0**

## What it is

`MongoDBFlowPersistence` subclasses `crewai.flow.persistence.base.FlowPersistence` (a Pydantic `BaseModel` + ABC in CrewAI 1.x) and stores CrewAI flow state in a MongoDB collection. Configuration (`connection_string`, `database_name`, `collection_name`, `messages_key`) is declared as Pydantic fields, while the runtime objects (the `MongoClient` and the reducer) are held as `PrivateAttr`. It accepts an optional [`MessageReducer`](../reducer/index.md) that prunes the message list at the persistence layer.

Persistence is keyed by the flow state's `id` field — the `flow_uuid`. One document is stored per flow run: each save upserts the latest state via `replace_one(..., upsert=True)`, so `load_state` returns the most recent. Flow state is stored as a nested BSON document under a `data` field. `save_state` accepts either a Pydantic `BaseModel` or a plain dict; `load_state` returns a dict (or `None`).

## Installation

=== "Base"

    ```bash
    pip install crewai-persistence-mongodb
    ```

=== "With pruning"

    ```bash
    pip install "crewai-persistence-mongodb[reducer]"
    ```

The `[reducer]` extra pulls in `agentstate-reducer`, required only if you pass a `reducer`.

## Database and collection setup

| Behaviour | Detail |
|---|---|
| **Database** | Created lazily by MongoDB on first write; no pre-provisioning needed |
| **Collection** | Created lazily on first write |
| **Index** | A unique index on `flow_uuid` is created by `init_db()` |

The backend calls `init_db()` from `__init__`, which resolves the collection and calls `create_index("flow_uuid", unique=True)`. MongoDB (and Azure Cosmos DB for MongoDB / DocumentDB) create the database and collection on demand, so no manual setup is required.

## Authentication

MongoDB authentication is carried in the connection string. Pass credentials in the URI, or hand the backend a pre-built `MongoClient`.

=== "Local (dev)"

    ```bash
    export MONGO_URI="mongodb://127.0.0.1:27017/"
    ```

=== "Atlas / SRV (prod)"

    ```bash
    export MONGO_URI="mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority"
    ```

=== "Pre-built client"

    Build a `MongoClient` yourself (custom TLS, pool, timeouts) and pass it as `client=`; the `connection_string` is then ignored.

    ```python
    from pymongo import MongoClient
    client = MongoClient("mongodb+srv://...", tls=True)
    ```

## Quick start

### Normal flow

```python
import os
from crewai.flow.flow import Flow, start, listen
from crewai.flow.persistence import persist
from crewai_persistence_mongodb import MongoDBFlowPersistence

persistence = MongoDBFlowPersistence(
    connection_string=os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/"),
    database_name="crewai_flows",
    collection_name="flow_states",
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
import os
from crewai.flow.flow import Flow, start, listen
from crewai.flow.persistence import persist
from agentstate_reducer import MessageReducer
from agentstate_reducer.models import ReducerConfig
from crewai_persistence_mongodb import MongoDBFlowPersistence

reducer = MessageReducer(config=ReducerConfig(min_messages=10, max_messages=20))

persistence = MongoDBFlowPersistence(
    connection_string=os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/"),
    database_name="crewai_flows",
    collection_name="flow_states",
    reducer=reducer,         # prune before each save
    messages_key="messages", # state key holding the message list (default)
)

@persist(persistence)
class ChatFlow(Flow):
    @start()
    def handle_turn(self):
        # messages accumulate here; pruning happens automatically at save time
        messages = self.state.get("messages", [])
        messages.append({"role": "human", "content": "Tell me about MongoDB."})
        # ... call your LLM here ...
        messages.append({"role": "ai", "content": "MongoDB is a document-oriented NoSQL database..."})
        return {"messages": messages}

flow = ChatFlow()
flow.kickoff()
```

!!! note "The `@persist` decorator"
    `@persist` is imported from `crewai.flow.persistence`. Applied to a `Flow` subclass with your persistence instance, it transparently calls `save_state` / `load_state` keyed by the flow state's `id` (the `flow_uuid`).

## API reference

### `MongoDBFlowPersistence(*, connection_string="mongodb://127.0.0.1:27017/", database_name="crewai_flows", collection_name="flow_states", client=None, reducer=None, messages_key="messages")`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `connection_string` | `str` | `"mongodb://127.0.0.1:27017/"` | MongoDB connection URI |
| `database_name` | `str` | `"crewai_flows"` | Database name |
| `collection_name` | `str` | `"flow_states"` | Collection name |
| `client` | `MongoClient \| None` | `None` | Pre-built client; if provided, `connection_string` is ignored |
| `reducer` | `MessageReducer \| None` | `None` | Optional pruner — see [Built-in message pruning](#built-in-message-pruning) |
| `messages_key` | `str` | `"messages"` | State key that holds the message list |

### Methods

| Method | Description |
|---|---|
| `init_db()` | Resolve the client/collection and ensure the unique `flow_uuid` index (called automatically by `__init__`) |
| `save_state(flow_uuid, method_name, state_data)` | Persist flow state (upsert by `flow_uuid` via `replace_one`); accepts a `BaseModel` or dict |
| `load_state(flow_uuid)` | Load the most recently saved state as a dict; returns `None` if not found |

## Built-in message pruning

Long-running conversational flows accumulate message history with every turn, inflating document size, increasing MongoDB storage costs, and eventually blowing past LLM context limits.

Pass a [`MessageReducer`](../reducer/index.md) and the backend prunes the message list inside `save_state()` before the document is written to MongoDB. **Your flow code and state model stay untouched.**

When `len(messages) > max_messages`, the oldest `human`/`ai` messages are removed until `min_messages` remain. System-prompt index 0, `system`/`function` messages, and `tool` messages (unless their parent `ai` message is pruned) are preserved.

!!! tip "Full reducer configuration"
    For `preserve_first`, `cascade_tool_messages`, `summarize_fn`, token budgeting, and role aliases, see the [reducer overview](../reducer/index.md) and [token budget](../reducer/token-budget.md) docs.

## Long-term memory via `on_prune`

!!! success "New in crewai-persistence-mongodb 0.2.0"
    Messages pruned from the flow state are exactly the ones leaving the model's view. The persistence layer forwards a **memory namespace** to the reducer, and any [`on_prune`](../reducer/long-term-memory.md) hook receives `(pruned_messages, namespace)` — so pruned turns can flow straight into CrewAI's unified `Memory` on a [cloud backend](memory.md), with no package coupling.

```python
from agentstate_reducer import MessageReducer, ReducerConfig, Background
from crewai.memory import Memory

memory = Memory(storage=...)                     # e.g. crewai-memory-mongodb

def remember(pruned, namespace):
    text = "
".join(m["content"] for m in pruned)
    memory.remember_many(memory.extract_memories(text), scope=namespace)   # LLM calls -> off the request path

reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))

class SupportState(BaseModel):
    id: str = ""
    memory_namespace: str = "/user/kamal"        # long-term scope: the USER, not the flow
    messages: list = []

@persist(MongoDBFlowPersistence(..., reducer=reducer))
class SupportFlow(Flow[SupportState]):
    ...
```

The persistence layer reads `memory_namespace` (or whatever `ReducerConfig.namespace_key` names) from the flow state on every `save_state` and passes it through untouched. If the state never sets it, the namespace falls back to `"/flow/<flow_uuid>"`. Each pruned message reaches the hooks once. Requires `agentstate-reducer>=0.4.0`.

## Data model

Each call to `save_state` upserts a single MongoDB document keyed by `flow_uuid`. Only the latest state for each flow run is stored (`replace_one` overwrites the matching document).

| Field | Description |
|---|---|
| `flow_uuid` | Unique identifier for the flow run (indexed, unique) |
| `data` | The full state dict, stored as a nested BSON document |
| `method_name` | Name of the flow method that triggered the save |
| `saved_at` | UTC `datetime` of the save |

!!! note "Nested document storage"
    Unlike JSON-string backends, the state dict is stored natively as a nested BSON document under `data`, so `load_state` returns `doc["data"]` directly.
