# CrewAI Persistence — SQL

A CrewAI `FlowPersistence` backend for **any SQLAlchemy database** (SQLite, PostgreSQL, MySQL, …) with **built-in message pruning**. It persists flow state between steps so your flows can resume from any saved checkpoint, and it can automatically cap your message history before each write — no changes to your flow code or state model required.

!!! note "Current version"
    `crewai-persistence-sql` **0.1.0** · Requires **Python >=3.10,<3.14** (CrewAI constraint), **crewai>=1.0.0**, and **SQLAlchemy>=2.0**

## What it is

`SQLFlowPersistence` subclasses `crewai.flow.persistence.base.FlowPersistence` (a Pydantic `BaseModel` + ABC in CrewAI 1.x) and stores CrewAI flow state in a single relational table via SQLAlchemy Core. Configuration (`url`, `table_name`, `messages_key`) is declared as Pydantic fields, while the runtime objects (the SQLAlchemy engine and the reducer) are held as `PrivateAttr`. One provider works for any SQLAlchemy-supported database. It accepts an optional [`MessageReducer`](../reducer/index.md) that prunes the message list at the persistence layer.

Persistence is keyed by the flow state's `id` field — the `flow_uuid`. One row is stored per flow run: each save upserts the latest state (an `UPDATE`, falling back to `INSERT` when no row matched), so `load_state` returns the most recent. Flow state is serialised to a JSON string in a `data` text column. `save_state` accepts either a Pydantic `BaseModel` or a plain dict; `load_state` returns a dict (or `None`).

## Installation

=== "Base"

    ```bash
    pip install crewai-persistence-sql
    ```

=== "With pruning"

    ```bash
    pip install "crewai-persistence-sql[reducer]"
    ```

The `[reducer]` extra pulls in `agentstate-reducer`, required only if you pass a `reducer`. Database drivers ship as extras too: `[postgres]` (psycopg 3) and `[mysql]` (PyMySQL). SQLite needs no extra driver.

## Database and table setup

| Behaviour | Detail |
|---|---|
| **Engine** | Built from `url` via `create_engine`, or supplied directly as `engine=` |
| **Table** | Created automatically by `init_db()` via `metadata.create_all` if absent |
| **Schema** | Two columns — `flow_uuid` (`String(255)`, primary key) and `data` (`Text`, not null) |

You must provide **either** `url` **or** `engine`; if both are omitted a `ValueError` is raised. The database itself (the PostgreSQL/MySQL server and target database) must already exist — SQLAlchemy creates the table, not the database.

## Connection URLs

The `url` is a standard SQLAlchemy connection string. Provide credentials inside the URL, or build the engine yourself and pass `engine=`.

=== "SQLite (dev)"

    ```bash
    export DB_URL="sqlite:///flows.db"
    ```

=== "PostgreSQL (prod)"

    ```bash
    export DB_URL="postgresql+psycopg://<user>:<password>@<host>:5432/<database>"
    ```

=== "MySQL"

    ```bash
    export DB_URL="mysql+pymysql://<user>:<password>@<host>:3306/<database>"
    ```

=== "Pre-built engine"

    Build the engine yourself (custom pool size, TLS, timeouts) and pass it as `engine=`; the `url` is then ignored.

    ```python
    from sqlalchemy import create_engine
    engine = create_engine("postgresql+psycopg://...", pool_size=10)
    ```

## Quick start

### Normal flow

```python
import os
from crewai.flow.flow import Flow, start, listen
from crewai.flow.persistence import persist
from crewai_persistence_sql import SQLFlowPersistence

persistence = SQLFlowPersistence(
    url=os.environ.get("DB_URL", "sqlite:///flows.db"),
    table_name="crewai_flow_states",
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
from crewai_persistence_sql import SQLFlowPersistence

reducer = MessageReducer(config=ReducerConfig(min_messages=10, max_messages=20))

persistence = SQLFlowPersistence(
    url=os.environ.get("DB_URL", "sqlite:///flows.db"),
    table_name="crewai_flow_states",
    reducer=reducer,         # prune before each save
    messages_key="messages", # state key holding the message list (default)
)

@persist(persistence)
class ChatFlow(Flow):
    @start()
    def handle_turn(self):
        # messages accumulate here; pruning happens automatically at save time
        messages = self.state.get("messages", [])
        messages.append({"role": "human", "content": "Tell me about SQL databases."})
        # ... call your LLM here ...
        messages.append({"role": "ai", "content": "A SQL database stores data in relational tables..."})
        return {"messages": messages}

flow = ChatFlow()
flow.kickoff()
```

!!! note "The `@persist` decorator"
    `@persist` is imported from `crewai.flow.persistence`. Applied to a `Flow` subclass with your persistence instance, it transparently calls `save_state` / `load_state` keyed by the flow state's `id` (the `flow_uuid`).

## API reference

### `SQLFlowPersistence(url=None, *, table_name="crewai_flow_states", engine=None, reducer=None, messages_key="messages")`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str \| None` | `None` | SQLAlchemy connection URL; required unless `engine` is given |
| `table_name` | `str` | `"crewai_flow_states"` | Table name (created if absent) |
| `engine` | `Engine \| None` | `None` | Pre-built SQLAlchemy engine; if provided, `url` is ignored |
| `reducer` | `MessageReducer \| None` | `None` | Optional pruner — see [Built-in message pruning](#built-in-message-pruning) |
| `messages_key` | `str` | `"messages"` | State key that holds the message list |

!!! warning "Provide `url` or `engine`"
    If neither `url` nor `engine` is supplied, `init_db()` raises `ValueError("Provide either 'url' or 'engine'")`.

### Methods

| Method | Description |
|---|---|
| `init_db()` | Build the engine (from `url`) and create the table if absent (called automatically by `__init__`) |
| `save_state(flow_uuid, method_name, state_data)` | Persist flow state (UPDATE then INSERT fallback, keyed by `flow_uuid`); accepts a `BaseModel` or dict |
| `load_state(flow_uuid)` | Load the most recently saved state as a dict; returns `None` if not found |

## Built-in message pruning

Long-running conversational flows accumulate message history with every turn, inflating row size, increasing storage costs, and eventually blowing past LLM context limits.

Pass a [`MessageReducer`](../reducer/index.md) and the backend prunes the message list inside `save_state()` before the row is written to the database. **Your flow code and state model stay untouched.**

When `len(messages) > max_messages`, the oldest `human`/`ai` messages are removed until `min_messages` remain. System-prompt index 0, `system`/`function` messages, and `tool` messages (unless their parent `ai` message is pruned) are preserved.

!!! tip "Full reducer configuration"
    For `preserve_first`, `cascade_tool_messages`, `summarize_fn`, token budgeting, and role aliases, see the [reducer overview](../reducer/index.md) and [token budget](../reducer/token-budget.md) docs.

## Long-term memory via `on_prune`

!!! success "New in crewai-persistence-sql 0.2.0"
    Messages pruned from the flow state are exactly the ones leaving the model's view. The persistence layer forwards a **memory namespace** to the reducer, and any [`on_prune`](../reducer/long-term-memory.md) hook receives `(pruned_messages, namespace)` — so pruned turns can flow straight into CrewAI's unified `Memory` on a [cloud backend](memory.md), with no package coupling.

```python
from agentstate_reducer import MessageReducer, ReducerConfig, Background
from crewai.memory import Memory

memory = Memory(storage=...)                     # e.g. crewai-memory-sql

def remember(pruned, namespace):
    text = "
".join(m["content"] for m in pruned)
    memory.remember_many(memory.extract_memories(text), scope=namespace)   # LLM calls -> off the request path

reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))

class SupportState(BaseModel):
    id: str = ""
    memory_namespace: str = "/user/kamal"        # long-term scope: the USER, not the flow
    messages: list = []

@persist(SQLFlowPersistence(..., reducer=reducer))
class SupportFlow(Flow[SupportState]):
    ...
```

The persistence layer reads `memory_namespace` (or whatever `ReducerConfig.namespace_key` names) from the flow state on every `save_state` and passes it through untouched. If the state never sets it, the namespace falls back to `"/flow/<flow_uuid>"`. Each pruned message reaches the hooks once. Requires `agentstate-reducer>=0.4.0`.

## Data model

Each call to `save_state` upserts a single row keyed by `flow_uuid`. Only the latest state for each flow run is stored (an `UPDATE` on the matching row, or an `INSERT` when none exists).

| Column | Type | Description |
|---|---|---|
| `flow_uuid` | `String(255)` (primary key) | Unique identifier for the flow run |
| `data` | `Text` (not null) | The full state dict serialised as a JSON string |

!!! note "JSON serialisation"
    The state dict is serialised into the `data` column as a JSON string; `load_state` parses it back into a dict. The `method_name` argument is accepted by `save_state` but not persisted — the table intentionally keeps a minimal two-column schema portable across SQLite, PostgreSQL, and MySQL.
