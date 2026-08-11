# PydanticAI Persistence

Backend-agnostic persistence for [PydanticAI](https://ai.pydantic.dev) — **chat history** and **durable step persistence** — over one small async KV interface. Every backend (DynamoDB, CosmosDB, Firestore) implements the same `AsyncKV` and gets both stores for free.

!!! note "Current version"
    `pydantic-ai-persistence` **0.1.0** · Requires **Python >=3.10** and **pydantic-ai>=1.0**

## Two persistence layers

PydanticAI has two distinct things worth persisting, and this family covers both:

| Layer | What it is | Store |
|---|---|---|
| **History** | You serialize `result.all_messages()` and store it yourself so a conversation can resume later. | `KVHistoryStore` |
| **Step persistence** | PydanticAI's `StepStore` — append-only events, continuable snapshots, and a tool-effect ledger for durable/resumable runs. | `KVStepStore` |

Both are built on a tiny four-method [`AsyncKV`](concepts.md) interface. Implement that once for a backend and you get history **and** step persistence together.

## The packages

| Package | Backend | PyPI |
|---|---|---|
| **[pydantic-ai-persistence](concepts.md)** | core + in-memory | `pydantic-ai-persistence` |
| **[pydantic-ai-dynamodb-persistence](dynamodb.md)** | AWS DynamoDB | `pydantic-ai-dynamodb-persistence` |
| **[pydantic-ai-cosmosdb-persistence](cosmosdb.md)** | Azure CosmosDB | `pydantic-ai-cosmosdb-persistence` |
| **[pydantic-ai-firestore-persistence](firestore.md)** | Google Firestore | `pydantic-ai-firestore-persistence` |

## Installation

The core package ships an in-memory backend. Add a cloud backend with an extra, or install the provider directly — both land the same packages.

=== "Via extras (recommended)"

    ```bash
    pip install "pydantic-ai-persistence[dynamodb]"
    pip install "pydantic-ai-persistence[cosmosdb]"
    pip install "pydantic-ai-persistence[firestore]"
    pip install "pydantic-ai-persistence[all]"     # every backend
    ```

=== "Direct provider"

    ```bash
    pip install pydantic-ai-dynamodb-persistence
    pip install pydantic-ai-cosmosdb-persistence
    pip install pydantic-ai-firestore-persistence
    ```

=== "Core only"

    ```bash
    pip install pydantic-ai-persistence   # in-memory backend, for tests/dev
    ```

## Quick taste

=== "History"

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

=== "Step persistence"

    ```python
    from pydantic_ai import Agent
    from pydantic_ai_harness.step_persistence import StepPersistence
    from pydantic_ai_dynamodb_persistence import DynamoDBStepStore

    step_store = DynamoDBStepStore(table_name="pai_persistence", max_snapshots_per_run=10)
    agent = Agent("openai:gpt-4o", capabilities=[StepPersistence(store=step_store)])
    ```

## Where to start

- New to the two layers? Read **[StepStore & History](concepts.md)**.
- Pick a backend: **[DynamoDB](dynamodb.md)** · **[CosmosDB](cosmosdb.md)** · **[Firestore](firestore.md)**.

!!! warning "Beta harness feature"
    PydanticAI's `StepStore` lives in `pydantic-ai-harness` and is a **beta/experimental** feature — its API may still change. The **history** layer (`KVHistoryStore`) is stable and independent of it.
