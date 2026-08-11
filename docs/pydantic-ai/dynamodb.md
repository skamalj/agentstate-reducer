# PydanticAI Persistence — DynamoDB

A PydanticAI **`StepStore`** and **message-history** store backed by **AWS DynamoDB**. Both stores share one DynamoDB table and one `AsyncKV` implementation — see [StepStore & History](concepts.md) for the layers.

!!! note "Current version"
    `pydantic-ai-dynamodb-persistence` **0.1.0** · Requires **Python >=3.10**, **pydantic-ai>=1.0**, and **boto3**

## What it is

`DynamoDBAsyncKV` implements the core [`AsyncKV`](concepts.md#the-asynckv-interface) over a single DynamoDB table (sync boto3 offloaded to a thread executor). On top of it:

- `DynamoDBStepStore` — PydanticAI's async `StepStore` (events, snapshots, tool-effect ledger).
- `DynamoDBHistoryStore` — `save`/`load` chat history by conversation id.

The table uses a `PK` (partition) / `SK` (sort) string key schema, billed **PAY_PER_REQUEST**, and is **auto-created** if absent.

## Installation

=== "Via extra"

    ```bash
    pip install "pydantic-ai-persistence[dynamodb]"
    ```

=== "Direct"

    ```bash
    pip install pydantic-ai-dynamodb-persistence
    ```

## Authentication

Credentials, region, and endpoint all resolve through the standard AWS chain (boto3), so nothing is hard-coded:

=== "Environment"

    ```bash
    export AWS_ACCESS_KEY_ID="..."
    export AWS_SECRET_ACCESS_KEY="..."
    export AWS_DEFAULT_REGION="us-east-1"
    ```

=== "Profile"

    ```python
    import boto3
    store = DynamoDBStepStore(
        table_name="pai_persistence",
        boto_session=boto3.Session(profile_name="my-profile"),
    )
    ```

=== "IAM role"

    On EC2/ECS/Lambda the instance/task role is used automatically — pass nothing extra.

=== "Local DynamoDB"

    ```python
    store = DynamoDBStepStore(
        table_name="pai_persistence",
        endpoint_url="http://localhost:8000",
        region_name="us-east-1",
    )
    ```

## Quick start

### History

```python
from pydantic_ai import Agent
from pydantic_ai_dynamodb_persistence import DynamoDBHistoryStore

agent = Agent("openai:gpt-4o")
store = DynamoDBHistoryStore(table_name="pai_persistence")

result = agent.run_sync("Hi, I'm Kamal")
await store.save("conv-1", result.all_messages())

prior = await store.load("conv-1")
result = agent.run_sync("What's my name?", message_history=prior)
```

### Step persistence

```python
from pydantic_ai import Agent
from pydantic_ai_harness.step_persistence import StepPersistence
from pydantic_ai_dynamodb_persistence import DynamoDBStepStore

step_store = DynamoDBStepStore(
    table_name="pai_persistence",
    region_name="us-east-1",
    max_snapshots_per_run=10,     # keep only the newest 10 snapshots per run
)
agent = Agent("openai:gpt-4o", capabilities=[StepPersistence(store=step_store)])
```

## API reference

### `DynamoDBStepStore(table_name, *, region_name=None, boto_session=None, endpoint_url=None, max_snapshots_per_run=None)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `table_name` | `str` | required | DynamoDB table name (auto-created if absent) |
| `region_name` | `str \| None` | `None` | AWS region; ignored if `boto_session` is passed |
| `boto_session` | `boto3.Session \| None` | `None` | Pre-built session (for profiles/custom credentials) |
| `endpoint_url` | `str \| None` | `None` | Override endpoint — e.g. local DynamoDB |
| `max_snapshots_per_run` | `int \| None` | `None` | Retain only the newest N snapshots per run; unbounded if `None` |

### `DynamoDBHistoryStore(table_name, *, region_name=None, boto_session=None, endpoint_url=None)`

Same connection parameters (no snapshot pruning — history is a single record per conversation).

### `DynamoDBAsyncKV(table_name, *, region_name=None, boto_session=None, endpoint_url=None)`

The raw KV layer if you want to build your own store on the same table.

## Data model

A single table with string keys `PK` (HASH) and `SK` (RANGE); each item also carries a `data` string attribute. `KVStepStore` maps runs, events, snapshots, and the tool ledger onto these keys — see the [key layout](concepts.md#key-layout).

!!! warning "Beta harness feature"
    `StepStore` is a **beta/experimental** PydanticAI harness feature; its API may still change. `DynamoDBHistoryStore` does not depend on it.
