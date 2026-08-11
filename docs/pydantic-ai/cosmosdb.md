# PydanticAI Persistence — CosmosDB

A PydanticAI **`StepStore`** and **message-history** store backed by **Azure CosmosDB**. Both stores share one Cosmos container and one `AsyncKV` implementation — see [StepStore & History](concepts.md) for the layers.

!!! note "Current version"
    `pydantic-ai-cosmosdb-persistence` **0.1.0** · Requires **Python >=3.10**, **pydantic-ai>=1.0**, and **azure-cosmos**

## What it is

`CosmosDBAsyncKV` implements the core [`AsyncKV`](concepts.md#the-asynckv-interface) over a CosmosDB container (sync azure-cosmos offloaded to a thread executor). On top of it:

- `CosmosDBStepStore` — PydanticAI's async `StepStore` (events, snapshots, tool-effect ledger).
- `CosmosDBHistoryStore` — `save`/`load` chat history by conversation id.

Items are `{id, PK, SK, data}` in a container partitioned by `/PK`. The Cosmos `id` is a URL-encoded `SK` (Cosmos ids can't contain `# / \ ?`); the raw `SK` is kept as a field for range queries. Database and container are **auto-created** under key-based auth.

## Installation

=== "Via extra"

    ```bash
    pip install "pydantic-ai-persistence[cosmosdb]"
    ```

=== "Direct"

    ```bash
    pip install pydantic-ai-cosmosdb-persistence
    ```

## Authentication

Key-based auth (auto-creates database and container):

```bash
export COSMOS_ENDPOINT="https://<account>.documents.azure.com:443/"
export COSMOS_KEY="<your-key>"
```

```python
import os
store = CosmosDBStepStore(
    endpoint=os.environ["COSMOS_ENDPOINT"],
    key=os.environ["COSMOS_KEY"],
    database_name="pai",
    container_name="steps",
)
```

!!! tip "Firewall"
    If your Cosmos account restricts network access, add your client IP to the account firewall (Azure Portal → Networking) or you'll get a `403 Forbidden`.

## Quick start

### History

```python
from pydantic_ai import Agent
from pydantic_ai_cosmosdb_persistence import CosmosDBHistoryStore

agent = Agent("openai:gpt-4o")
store = CosmosDBHistoryStore(
    endpoint="https://<account>.documents.azure.com:443/",
    key="<key>", database_name="pai", container_name="steps",
)

result = agent.run_sync("Hi, I'm Kamal")
await store.save("conv-1", result.all_messages())

prior = await store.load("conv-1")
result = agent.run_sync("What's my name?", message_history=prior)
```

### Step persistence

```python
from pydantic_ai import Agent
from pydantic_ai_harness.step_persistence import StepPersistence
from pydantic_ai_cosmosdb_persistence import CosmosDBStepStore

step_store = CosmosDBStepStore(
    endpoint="https://<account>.documents.azure.com:443/",
    key="<key>", database_name="pai", container_name="steps",
    max_snapshots_per_run=10,
)
agent = Agent("openai:gpt-4o", capabilities=[StepPersistence(store=step_store)])
```

## API reference

### `CosmosDBStepStore(*, endpoint, key, database_name, container_name, max_snapshots_per_run=None)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `endpoint` | `str` | required | CosmosDB account endpoint URL |
| `key` | `str` | required | Account key (key-based auth) |
| `database_name` | `str` | required | Database name (auto-created) |
| `container_name` | `str` | required | Container name (auto-created, partitioned by `/PK`) |
| `max_snapshots_per_run` | `int \| None` | `None` | Retain only the newest N snapshots per run; unbounded if `None` |

### `CosmosDBHistoryStore(*, endpoint, key, database_name, container_name)`

Same connection parameters (no snapshot pruning — history is a single record per conversation).

### `CosmosDBAsyncKV(*, endpoint, key, database_name, container_name)`

The raw KV layer if you want to build your own store on the same container.

## Data model

A container partitioned by `/PK`; each item is `{id, PK, SK, data}` (the `id` is a URL-encoded `SK`, the raw `SK` a field for `STARTSWITH` range queries with `ORDER BY c.SK`). `KVStepStore` maps runs, events, snapshots, and the tool ledger onto these keys — see the [key layout](concepts.md#key-layout).

!!! warning "Beta harness feature"
    `StepStore` is a **beta/experimental** PydanticAI harness feature; its API may still change. `CosmosDBHistoryStore` does not depend on it.
