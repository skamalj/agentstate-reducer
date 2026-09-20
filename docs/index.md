# Agent State Management

A growing, one-stop toolkit for managing **AI agent state** — keeping conversation history lean and persisting agent state across runs. Framework-agnostic at the core, with ready-made integrations for **LangGraph**, **CrewAI**, **PydanticAI**, and **Strands**.

## The Problem

Long-running agents accumulate message history with every turn. Left unchecked this:

- inflates persisted state size and storage cost,
- slows down serialization and retrieval, and
- eventually blows past the LLM's context window.

You also need that state to **survive between runs** — so a conversation can resume tomorrow exactly where it stopped today.

This toolkit solves both: **pruning** (keep history lean) and **persistence** (store and resume state) — and lets you combine them so pruning happens automatically at the persistence layer.

!!! success "New: pruning → long-term memory, with no package coupling"
    `agentstate-reducer` 0.4.0 adds **[`on_prune` hooks](reducer/long-term-memory.md)**: messages leaving the context window are handed to any callable — a LangGraph `BaseStore`, LangMem, a Strands `MemoryStore`, your own engine — at the exact moment they stop being visible to the model. The LangGraph checkpointers forward a per-call **memory namespace** (the *user*, not the thread) so short-term and long-term scopes stay separate. Exactly-once delivery and an off-request-path `Background` wrapper are built in.

## The Packages

### Pruning core

| Package | What it does | PyPI |
|---|---|---|
| **[agentstate-reducer](reducer/index.md)** | Framework-agnostic message pruning — by message count or token budget — plus **[`on_prune` long-term memory hooks](reducer/long-term-memory.md)** | `agentstate-reducer` |

### LangGraph checkpointers (with built-in pruning)

| Package | Backend | PyPI |
|---|---|---|
| **[langgraph-checkpoint-cosmosdb](langgraph/cosmosdb.md)** | Azure CosmosDB | `langgraph-checkpoint-cosmosdb` |
| **[langgraph-checkpoint-firestore](langgraph/firestore.md)** | Google Firestore | `langgraph-checkpoint-firestore` |
| **[langgraph-dynamodb-checkpoint](langgraph/dynamodb.md)** | AWS DynamoDB | `langgraph-dynamodb-checkpoint` |

### LangGraph stores — long-term memory (with native semantic search)

| Package | Backend | PyPI |
|---|---|---|
| **[langgraph-store-core](langgraph/stores.md)** | shared base + `IndexConfig` semantic search | `langgraph-store-core` |
| **[langgraph-store-dynamodb](langgraph/stores.md)** | AWS DynamoDB (native `SearchVectors`) | `langgraph-store-dynamodb` |
| **[langgraph-store-postgres](langgraph/stores.md)** | PostgreSQL (pgvector) | `langgraph-store-postgres` |
| **[langgraph-store-cosmosdb](langgraph/stores.md)** | Azure Cosmos DB (`VectorDistance`) | `langgraph-store-cosmosdb` |
| **[langgraph-store-firestore](langgraph/stores.md)** | Google Firestore (`find_nearest`) | `langgraph-store-firestore` |

### CrewAI Flow persistence (with built-in pruning)

| Package | Backend | PyPI |
|---|---|---|
| **[crewai-persistence-cosmosdb](crewai/cosmosdb.md)** | Azure CosmosDB | `crewai-persistence-cosmosdb` |
| **[crewai-persistence-firestore](crewai/firestore.md)** | Google Firestore | `crewai-persistence-firestore` |
| **[crewai-persistence-dynamodb](crewai/dynamodb.md)** | AWS DynamoDB | `crewai-persistence-dynamodb` |
| **[crewai-persistence-mongodb](crewai/mongodb.md)** | MongoDB | `crewai-persistence-mongodb` |
| **[crewai-persistence-sql](crewai/sql.md)** | Any SQLAlchemy DB | `crewai-persistence-sql` |

### CrewAI memory backends — long-term memory (with native vector search)

| Package | Backend | PyPI |
|---|---|---|
| **[crewai-memory-core](crewai/memory.md)** | shared base for CrewAI `StorageBackend`s | `crewai-memory-core` |
| **[crewai-memory-dynamodb](crewai/memory.md)** | AWS DynamoDB (native `SearchVectors`) | `crewai-memory-dynamodb` |
| **[crewai-memory-postgres](crewai/memory.md)** | PostgreSQL (pgvector) | `crewai-memory-postgres` |
| **[crewai-memory-cosmosdb](crewai/memory.md)** | Azure Cosmos DB (`VectorDistance`) | `crewai-memory-cosmosdb` |
| **[crewai-memory-firestore](crewai/memory.md)** | Google Firestore (`find_nearest`) | `crewai-memory-firestore` |

### PydanticAI persistence (StepStore + history)

| Package | Backend | PyPI |
|---|---|---|
| **[pydantic-ai-persistence](pydantic-ai/index.md)** | core + in-memory | `pydantic-ai-persistence` |
| **[pydantic-ai-dynamodb-persistence](pydantic-ai/dynamodb.md)** | AWS DynamoDB | `pydantic-ai-dynamodb-persistence` |
| **[pydantic-ai-cosmosdb-persistence](pydantic-ai/cosmosdb.md)** | Azure CosmosDB | `pydantic-ai-cosmosdb-persistence` |
| **[pydantic-ai-firestore-persistence](pydantic-ai/firestore.md)** | Google Firestore | `pydantic-ai-firestore-persistence` |

### PydanticAI memory backends — long-term memory (harness `MemoryStore`)

| Package | Backend | PyPI |
|---|---|---|
| **[pydantic-ai-memory-core](pydantic-ai/memory.md)** | shared base for harness `MemoryStore`s (CAS + receipts) | `pydantic-ai-memory-core` |
| **[pydantic-ai-dynamodb-memory](pydantic-ai/memory.md)** | AWS DynamoDB (conditional writes) | `pydantic-ai-dynamodb-memory` |
| **[pydantic-ai-cosmosdb-memory](pydantic-ai/memory.md)** | Azure Cosmos DB (ETag CAS) | `pydantic-ai-cosmosdb-memory` |
| **[pydantic-ai-firestore-memory](pydantic-ai/memory.md)** | Google Firestore (transactions) | `pydantic-ai-firestore-memory` |
| **[pydantic-ai-postgres-memory](pydantic-ai/memory.md)** | PostgreSQL (upstream store, from a URL) | `pydantic-ai-postgres-memory` |

### Strands sessions

| Package | Backend | PyPI |
|---|---|---|
| **[strands-agents-session](strands/index.md)** | core (session manager) | `strands-agents-session` |
| **[strands-agents-session\[dynamodb\]](strands/providers/dynamodb.md)** | AWS DynamoDB | `strands-agents-session-dynamodb` |
| **[strands-agents-session\[mongodb\]](strands/providers/mongodb.md)** | MongoDB | `strands-agents-session-mongodb` |
| **[strands-agents-session\[sql\]](strands/providers/sql.md)** | Any SQLAlchemy DB | `strands-agents-session-sql` |

!!! note "Growing toolkit"
    This is an evolving collection. More backends and framework integrations will be added over time. The common thread is the **`agentstate-reducer`** core — every pruning-aware persistence integration can optionally use it to prune state before writing. (The PydanticAI and Strands families focus on durable persistence and session management; pruning there is handled by each framework's own mechanisms.)

## How They Fit Together

```
                    ┌─────────────────────────┐
                    │    agentstate-reducer    │   ← pruning core (no deps)
                    │  message-count │ tokens  │
                    │  on_prune ──► long-term  │   ← pruned msgs → any store
                    └───────────┬─────────────┘
                                │ optional reducer= param
             ┌──────────────────┴──────────────────┐
             │                                      │
    ┌────────▼────────┐                    ┌────────▼────────┐
    │ LangGraph        │                    │ CrewAI          │
    │ checkpointers    │                    │ Flow persistence│
    │ Cosmos·Fire·Dynamo│                    │ Cosmos·Fire·Dynamo│
    └─────────────────┘                    │ ·Mongo·SQL      │
                                           └─────────────────┘

    ┌──────────────────────┐        ┌──────────────────────┐
    │ PydanticAI           │        │ Strands sessions     │
    │ StepStore + history  │        │ session manager      │
    │ Dynamo·Cosmos·Fire   │        │ Dynamo·Mongo·SQL     │
    └──────────────────────┘        └──────────────────────┘
       (own persistence layers; framework-native state handling)
```

The reducer is usable **standalone** (e.g. LangGraph's `Annotated[list, fn]` pattern), or **embedded** in the LangGraph/CrewAI persistence integrations via a `reducer=` parameter. Embedded, its **[`on_prune` hooks](reducer/long-term-memory.md)** turn every prune into a long-term-memory write, with the integration forwarding the app's memory namespace. The **PydanticAI** and **Strands** families provide durable persistence and session storage that fit each framework's native state model.

## Quick Taste

=== "Standalone pruning"

    ```python
    from agentstate_reducer import MessageReducer

    reducer = MessageReducer(min_messages=10, max_messages=20)
    result = reducer.reduce(existing=messages, new=new_messages)
    print(result.surviving)  # capped list
    ```

=== "LangGraph + CosmosDB"

    ```python
    from agentstate_reducer import MessageReducer
    from langgraph_checkpoint_cosmosdb import CosmosDBSaver

    saver = CosmosDBSaver(
        database_name="mydb",
        container_name="checkpoints",
        reducer=MessageReducer(min_messages=10, max_messages=20),
    )
    ```

=== "Pruned → long-term memory"

    ```python
    from agentstate_reducer import MessageReducer, ReducerConfig
    from langgraph_dynamodb_checkpoint import DynamoDBSaver

    def remember(pruned, namespace):          # any BaseStore / LangMem / engine
        for m in pruned:
            store.put(namespace, key=m.id, value={"content": m.content})

    saver = DynamoDBSaver("checkpoints",
        reducer=MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[remember])))

    graph.invoke(input, config={"configurable": {
        "thread_id": thread_id,                          # short-term scope
        "memory_namespace": ("memories", user_id),       # long-term scope
    }})
    ```

=== "CrewAI + Firestore"

    ```python
    from crewai.flow.persistence import persist
    from crewai_persistence_firestore import FirestoreFlowPersistence
    from agentstate_reducer import MessageReducer

    @persist(FirestoreFlowPersistence(
        project_id="my-project",
        reducer=MessageReducer(min_messages=10, max_messages=20),
    ))
    class MyFlow(Flow[MyState]):
        ...
    ```

## Where to Start

- New to the concepts? Read the **[State Management Overview](concepts/overview.md)**.
- Not sure which package you need? See **[Choosing an Approach](concepts/choosing.md)**.
- Just want pruning? Go to **[agentstate-reducer](reducer/index.md)**.
- Want pruned history to become long-term memory? Read **[Long-Term Memory Hooks](reducer/long-term-memory.md)**.
