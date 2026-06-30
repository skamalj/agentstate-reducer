# Choosing an Approach

A quick decision guide for picking the right package(s).

## Which framework are you using?

```
Are you using LangGraph or CrewAI?
│
├─ LangGraph ──► langgraph-checkpoint-{cosmosdb|firestore}
│
├─ CrewAI Flows ──► crewai-persistence-{cosmosdb|firestore}
│
└─ Neither / custom ──► agentstate-reducer (standalone pruning)
```

## Which cloud?

| You use… | Pick |
|---|---|
| Azure | the `cosmosdb` variant |
| Google Cloud | the `firestore` variant |
| Neither yet | start with [agentstate-reducer](../reducer/index.md) standalone; add persistence later |

## Do you need pruning, persistence, or both?

| Need | Use |
|---|---|
| Just cap history, no storage | `agentstate-reducer` standalone |
| Just store/resume state, no capping | persistence package **without** a `reducer` |
| Store **and** cap automatically | persistence package **with** a `reducer` |

## Message-count vs token-budget pruning

| Choose… | When |
|---|---|
| **Message count** (`min_messages`/`max_messages`) | You want simple, predictable limits and roughly uniform message sizes |
| **Token budget** (`max_tokens`/`target_tokens`) | You care about the model's context window or cost, and message sizes vary a lot |

See [Message-Count Pruning](../reducer/message-count.md) and [Token-Budget Pruning](../reducer/token-budget.md) for details.

## Where should pruning run?

| Choose… | When |
|---|---|
| **In-graph** (`as_langgraph_reducer()`) | You own the LangGraph state definition and want pruning on every merge |
| **At persistence** (`reducer=` param) | You use a prebuilt agent, don't own the state, or want to keep full in-memory state and only prune what's stored |

## Common combinations

=== "LangGraph agent on Azure, token-aware"

    ```python
    from agentstate_reducer import MessageReducer, ReducerConfig
    from langgraph_checkpoint_cosmosdb import CosmosDBSaver

    saver = CosmosDBSaver(
        database_name="mydb",
        container_name="checkpoints",
        reducer=MessageReducer(config=ReducerConfig(max_tokens=4000, target_tokens=2000)),
    )
    ```

=== "CrewAI conversational flow on GCP"

    ```python
    from crewai.flow.persistence import persist
    from crewai_persistence_firestore import FirestoreFlowPersistence
    from agentstate_reducer import MessageReducer

    @persist(FirestoreFlowPersistence(
        project_id="my-project",
        reducer=MessageReducer(min_messages=10, max_messages=20),
    ))
    class ChatFlow(Flow[ChatState]):
        ...
    ```

=== "Custom framework, pruning only"

    ```python
    from agentstate_reducer import MessageReducer

    reducer = MessageReducer(min_messages=10, max_messages=20)
    kept = reducer.reduce(existing=history, new=[new_msg]).surviving
    ```
