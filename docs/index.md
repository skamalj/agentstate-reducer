# Agent State Management

A growing, one-stop toolkit for managing **AI agent state** — keeping conversation history lean and persisting agent state across runs. Framework-agnostic at the core, with ready-made integrations for **LangGraph**, **CrewAI**, **PydanticAI**, and **Strands**.

## The Problem

Long-running agents accumulate message history with every turn. Left unchecked this:

- inflates persisted state size and storage cost,
- slows down serialization and retrieval, and
- eventually blows past the LLM's context window.

You also need that state to **survive between runs** — so a conversation can resume tomorrow exactly where it stopped today.

This toolkit solves both: **pruning** (keep history lean) and **persistence** (store and resume state) — and lets you combine them so pruning happens automatically at the persistence layer.

## The Packages

### Pruning core

| Package | What it does | PyPI |
|---|---|---|
| **[agentstate-reducer](reducer/index.md)** | Framework-agnostic message pruning — by message count or token budget | `agentstate-reducer` |

### LangGraph checkpointers (with built-in pruning)

| Package | Backend | PyPI |
|---|---|---|
| **[langgraph-checkpoint-cosmosdb](langgraph/cosmosdb.md)** | Azure CosmosDB | `langgraph-checkpoint-cosmosdb` |
| **[langgraph-checkpoint-firestore](langgraph/firestore.md)** | Google Firestore | `langgraph-checkpoint-firestore` |
| **[langgraph-dynamodb-checkpoint](langgraph/dynamodb.md)** | AWS DynamoDB | `langgraph-dynamodb-checkpoint` |

### CrewAI Flow persistence (with built-in pruning)

| Package | Backend | PyPI |
|---|---|---|
| **[crewai-persistence-cosmosdb](crewai/cosmosdb.md)** | Azure CosmosDB | `crewai-persistence-cosmosdb` |
| **[crewai-persistence-firestore](crewai/firestore.md)** | Google Firestore | `crewai-persistence-firestore` |
| **[crewai-persistence-dynamodb](crewai/dynamodb.md)** | AWS DynamoDB | `crewai-persistence-dynamodb` |
| **[crewai-persistence-mongodb](crewai/mongodb.md)** | MongoDB | `crewai-persistence-mongodb` |
| **[crewai-persistence-sql](crewai/sql.md)** | Any SQLAlchemy DB | `crewai-persistence-sql` |

### PydanticAI persistence (StepStore + history)

| Package | Backend | PyPI |
|---|---|---|
| **[pydantic-ai-persistence](pydantic-ai/index.md)** | core + in-memory | `pydantic-ai-persistence` |
| **[pydantic-ai-dynamodb-persistence](pydantic-ai/dynamodb.md)** | AWS DynamoDB | `pydantic-ai-dynamodb-persistence` |
| **[pydantic-ai-cosmosdb-persistence](pydantic-ai/cosmosdb.md)** | Azure CosmosDB | `pydantic-ai-cosmosdb-persistence` |
| **[pydantic-ai-firestore-persistence](pydantic-ai/firestore.md)** | Google Firestore | `pydantic-ai-firestore-persistence` |

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

The reducer is usable **standalone** (e.g. LangGraph's `Annotated[list, fn]` pattern), or **embedded** in the LangGraph/CrewAI persistence integrations via a `reducer=` parameter. The **PydanticAI** and **Strands** families provide durable persistence and session storage that fit each framework's native state model.

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
