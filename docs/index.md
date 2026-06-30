# Agent State Management

A growing, one-stop toolkit for managing **AI agent state** — keeping conversation history lean and persisting agent state across runs. Framework-agnostic at the core, with ready-made integrations for **LangGraph** and **CrewAI**.

## The Problem

Long-running agents accumulate message history with every turn. Left unchecked this:

- inflates persisted state size and storage cost,
- slows down serialization and retrieval, and
- eventually blows past the LLM's context window.

You also need that state to **survive between runs** — so a conversation can resume tomorrow exactly where it stopped today.

This toolkit solves both: **pruning** (keep history lean) and **persistence** (store and resume state) — and lets you combine them so pruning happens automatically at the persistence layer.

## The Packages

| Package | What it does | PyPI |
|---|---|---|
| **[agentstate-reducer](reducer/index.md)** | Framework-agnostic message pruning — by message count or token budget | `agentstate-reducer` |
| **[langgraph-checkpoint-cosmosdb](langgraph/cosmosdb.md)** | LangGraph checkpoint saver for Azure CosmosDB, with built-in pruning | `langgraph-checkpoint-cosmosdb` |
| **[langgraph-checkpoint-firestore](langgraph/firestore.md)** | LangGraph checkpoint saver for Google Firestore, with built-in pruning | `langgraph-checkpoint-firestore` |
| **[crewai-persistence-cosmosdb](crewai/cosmosdb.md)** | CrewAI Flow persistence backend for Azure CosmosDB, with built-in pruning | `crewai-persistence-cosmosdb` |
| **[crewai-persistence-firestore](crewai/firestore.md)** | CrewAI Flow persistence backend for Google Firestore, with built-in pruning | `crewai-persistence-firestore` |

!!! note "Growing toolkit"
    This is an evolving collection. More backends and framework integrations will be added over time. The common thread is the **`agentstate-reducer`** core — every persistence integration can optionally use it to prune state before writing.

## How They Fit Together

```
                  ┌─────────────────────────┐
                  │    agentstate-reducer    │   ← pruning core (no deps)
                  │  message-count │ tokens  │
                  └───────────┬─────────────┘
                              │ used by (optional) reducer= param
          ┌───────────────────┼────────────────────┐
          │                   │                    │
 ┌────────▼────────┐ ┌────────▼────────┐  ┌────────▼─────────┐
 │ LangGraph        │ │ CrewAI          │  │  (your own        │
 │ checkpointers    │ │ persistence     │  │   integration)    │
 │ Cosmos │ Firestore│ │ Cosmos│Firestore│  └──────────────────┘
 └─────────────────┘ └─────────────────┘
```

The reducer is usable **standalone** (e.g. LangGraph's `Annotated[list, fn]` pattern), or **embedded** in any of the persistence integrations via a `reducer=` parameter.

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
