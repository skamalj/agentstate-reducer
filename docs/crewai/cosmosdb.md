# CrewAI Persistence — CosmosDB

A CrewAI `FlowPersistence` backend for **Azure CosmosDB** with **built-in message pruning**. It persists flow state between steps so your flows can resume from any saved checkpoint, and it can automatically cap your message history before each write — no changes to your flow code or state model required.

!!! note "Current version"
    `crewai-persistence-cosmosdb` **0.1.0** · Requires **Python >=3.10,<3.14** (CrewAI constraint) and **crewai>=1.0.0**

## What it is

`CosmosDBFlowPersistence` subclasses `crewai.flow.persistence.base.FlowPersistence` (a Pydantic `BaseModel` + ABC in CrewAI 1.x) and stores CrewAI flow state in an Azure CosmosDB container. Unlike other CosmosDB backends, it accepts an optional [`MessageReducer`](../reducer/index.md) that prunes the message list at the persistence layer.

Persistence is keyed by the flow state's `id` field — the `flow_uuid`. `save_state` accepts either a Pydantic `BaseModel` or a plain dict; `load_state` returns a dict (or `None`).

## Installation

=== "Base"

    ```bash
    pip install crewai-persistence-cosmosdb
    ```

=== "With pruning"

    ```bash
    pip install "crewai-persistence-cosmosdb[reducer]"
    ```

The `[reducer]` extra pulls in `agentstate-reducer`, required only if you pass a `reducer`.

## Database and container setup

| Auth mode | Database | Container | Partition key |
|---|---|---|---|
| **Key-based** (`key=` passed) | Created automatically if absent | Created automatically if absent | `/flow_uuid` (set by the backend) |
| **RBAC / Managed Identity** (no key) | **Must pre-exist** | **Must pre-exist** | `/flow_uuid` (must be pre-configured) |

Key-based auth auto-creates everything. For RBAC, the backend only calls `get_database_client` / `get_container_client` (no setup-time write permissions), so provision the database and container first:

```bash
az cosmosdb sql database create --account-name <account> --name <db>
az cosmosdb sql container create \
  --account-name <account> --database-name <db> --name <container> \
  --partition-key-path "/flow_uuid"
```

!!! warning "Partition key path"
    The partition key path **must** be `/flow_uuid` regardless of how the container is created.

## Authentication

=== "Key-based (dev)"

    ```bash
    export COSMOS_ENDPOINT="https://<account>.documents.azure.com:443/"
    export COSMOS_KEY="<your-key>"
    ```

=== "Azure RBAC (prod)"

    Omit `key=`. The backend uses `DefaultAzureCredential`, resolving in order: environment service principal → managed identity → `az login`.

    ```bash
    export COSMOS_ENDPOINT="https://<account>.documents.azure.com:443/"
    # COSMOS_KEY not set → DefaultAzureCredential is used
    ```

=== "Service principal"

    ```bash
    export AZURE_TENANT_ID="<tenant-id>"
    export AZURE_CLIENT_ID="<client-id>"
    export AZURE_CLIENT_SECRET="<client-secret>"
    ```

## Quick start

### Normal flow

```python
import os
from crewai.flow.flow import Flow, start, listen
from crewai.flow.persistence import persist
from crewai_persistence_cosmosdb import CosmosDBFlowPersistence

persistence = CosmosDBFlowPersistence(
    endpoint=os.environ["COSMOS_ENDPOINT"],
    database_name="mydb",
    container_name="flow_states",
    key=os.environ.get("COSMOS_KEY"),   # omit for RBAC
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
from crewai_persistence_cosmosdb import CosmosDBFlowPersistence

reducer = MessageReducer(config=ReducerConfig(min_messages=10, max_messages=20))

persistence = CosmosDBFlowPersistence(
    endpoint=os.environ["COSMOS_ENDPOINT"],
    database_name="mydb",
    container_name="flow_states",
    key=os.environ.get("COSMOS_KEY"),
    reducer=reducer,         # prune before each save
    messages_key="messages", # state key holding the message list (default)
)

@persist(persistence)
class ChatFlow(Flow):
    @start()
    def handle_turn(self):
        # messages accumulate here; pruning happens automatically at save time
        messages = self.state.get("messages", [])
        messages.append({"role": "human", "content": "Tell me about Azure CosmosDB."})
        # ... call your LLM here ...
        messages.append({"role": "ai", "content": "CosmosDB is a globally distributed NoSQL database..."})
        return {"messages": messages}

flow = ChatFlow()
flow.kickoff()
```

!!! note "The `@persist` decorator"
    `@persist` is imported from `crewai.flow.persistence`. Applied to a `Flow` subclass with your persistence instance, it transparently calls `save_state` / `load_state` keyed by the flow state's `id` (the `flow_uuid`).

## API reference

### `CosmosDBFlowPersistence(endpoint, database_name, container_name, key=None, reducer=None, messages_key="messages")`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `endpoint` | `str` | required | CosmosDB account endpoint URL |
| `database_name` | `str` | required | CosmosDB database name |
| `container_name` | `str` | required | CosmosDB container name |
| `key` | `str \| None` | `None` | Account key; omit to use `DefaultAzureCredential` (RBAC) |
| `reducer` | `MessageReducer \| None` | `None` | Optional pruner — see [Built-in message pruning](#built-in-message-pruning) |
| `messages_key` | `str` | `"messages"` | State key that holds the message list |

### Methods

| Method | Description |
|---|---|
| `init_db()` | Initialise database/container references (called automatically by `__init__`) |
| `save_state(flow_uuid, method_name, state_data)` | Persist flow state (upsert by `flow_uuid`); accepts a `BaseModel` or dict |
| `load_state(flow_uuid)` | Load the most recently saved state as a dict; returns `None` if not found |

## Built-in message pruning

Long-running conversational flows accumulate message history with every turn, inflating document size, increasing CosmosDB storage costs, and eventually blowing past LLM context limits.

Pass a [`MessageReducer`](../reducer/index.md) and the backend prunes the message list inside `save_state()` before the document is written to CosmosDB. **Your flow code and state model stay untouched.**

When `len(messages) > max_messages`, the oldest `human`/`ai` messages are removed until `min_messages` remain. System-prompt index 0, `system`/`function` messages, and `tool` messages (unless their parent `ai` message is pruned) are preserved.

!!! tip "Full reducer configuration"
    For `preserve_first`, `cascade_tool_messages`, `summarize_fn`, token budgeting, and role aliases, see the [reducer overview](../reducer/index.md) and [token budget](../reducer/token-budget.md) docs.

## Long-term memory via `on_prune`

!!! success "New in crewai-persistence-cosmosdb 0.2.0"
    Messages pruned from the flow state are exactly the ones leaving the model's view. The persistence layer forwards a **memory namespace** to the reducer, and any [`on_prune`](../reducer/long-term-memory.md) hook receives `(pruned_messages, namespace)` — so pruned turns can flow straight into CrewAI's unified `Memory` on a [cloud backend](memory.md), with no package coupling.

```python
from agentstate_reducer import MessageReducer, ReducerConfig, Background
from crewai.memory import Memory

memory = Memory(storage=...)                     # e.g. crewai-memory-cosmosdb

def remember(pruned, namespace):
    text = "
".join(m["content"] for m in pruned)
    memory.remember_many(memory.extract_memories(text), scope=namespace)   # LLM calls -> off the request path

reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))

class SupportState(BaseModel):
    id: str = ""
    memory_namespace: str = "/user/kamal"        # long-term scope: the USER, not the flow
    messages: list = []

@persist(CosmosDBFlowPersistence(..., reducer=reducer))
class SupportFlow(Flow[SupportState]):
    ...
```

The persistence layer reads `memory_namespace` (or whatever `ReducerConfig.namespace_key` names) from the flow state on every `save_state` and passes it through untouched. If the state never sets it, the namespace falls back to `"/flow/<flow_uuid>"`. Each pruned message reaches the hooks once. Requires `agentstate-reducer>=0.4.0`.

## Data model

Each call to `save_state` upserts a single CosmosDB document partitioned by `flow_uuid`. Only the latest state for each flow run is stored (upsert overwrites on `id = flow_uuid`).

| Field | Description |
|---|---|
| `id` | Same as `flow_uuid` (CosmosDB document id) |
| `flow_uuid` | Unique identifier for the flow run (partition key) |
| `_method_name` | Name of the flow method that triggered the save |
| `_saved_at` | ISO-8601 UTC timestamp of the save |
| _user fields_ | All fields from the original state dict / Pydantic model |

!!! note "Metadata handling"
    Persistence metadata is stored under `_persistence_meta` and stripped on load. CosmosDB system fields (`_rid`, `_self`, `_etag`, `_attachments`, `_ts`) are also stripped before `load_state` returns the document.
