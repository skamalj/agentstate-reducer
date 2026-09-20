# Plugging an extractor into the `on_prune` hook

We ship checkpointers and stores. We deliberately ship **no extractor**: LangMem, CrewAI's memory engine and Strands' extractor already turn conversation into facts, and they keep improving. The reducer's `on_prune` hook is the socket they plug into.

The hook is a plain callable, `hook(pruned_messages, namespace)`. It fires once per message, the moment that message leaves the context window, from inside whichever checkpointer or persistence layer runs the reducer. Anything slow, which means any LLM call, goes inside `Background(...)` so it runs off the request path.

Every snippet below has the same shape: build the extractor, write a few lines that call it, register that function as the reducer's `on_prune` hook. Snippets marked *tested* mirror an end-to-end test that ships in the corresponding repo.

=== "LangGraph + LangMem"

    ```python
    from langmem import create_memory_store_manager
    from agentstate_reducer import MessageReducer, ReducerConfig, Background
    from langgraph_store_postgres import PostgresStore
    from langgraph_dynamodb_checkpoint import DynamoDBSaver

    store = PostgresStore(url, index={"dims": 1024, "embed": embedder, "fields": ["content"]})   # LangMem needs an index
    manager = create_memory_store_manager("anthropic:claude-sonnet-5", namespace=("memories", "{user_id}"))

    def remember(pruned, namespace):                       # the reducer's on_prune hook
        manager.invoke({"messages": pruned}, config={"configurable": {"user_id": namespace[-1]}})

    reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))
    saver = DynamoDBSaver("checkpoints", reducer=reducer)
    graph = builder.compile(checkpointer=saver, store=store)

    graph.invoke(input, config={"configurable": {"thread_id": tid, "memory_namespace": ("memories", user_id)}})
    ```

    LangMem extracts, consolidates and writes into the store; the reducer only replaced its clock. LangMem is dormant upstream and never passes `index=` itself, so build the store with an `IndexConfig` — see [LangGraph Stores](../langgraph/stores.md).

=== "CrewAI Memory engine (tested)"

    ```python
    from crewai.memory import Memory
    from crewai_memory_dynamodb import DynamoDBMemoryBackend
    from agentstate_reducer import MessageReducer, ReducerConfig, Background

    memory = Memory(storage=DynamoDBMemoryBackend("crewai-memory", dimensions=3072))

    def remember(pruned, namespace):                       # the reducer's on_prune hook
        text = "\n".join(m["content"] for m in pruned)
        memory.remember_many(memory.extract_memories(text), scope=namespace)

    reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))

    class SupportState(BaseModel):
        id: str = ""
        memory_namespace: str = "/user/kamal"              # a CrewAI Memory scope path
        messages: list = []

    @persist(DynamoDBFlowPersistence(table_name="flows", reducer=reducer))
    class SupportFlow(Flow[SupportState]): ...
    ```

    `extract_memories` and `remember_many` are CrewAI's own LLM analysis, scoping and consolidation. See [CrewAI Memory Backends](../crewai/memory.md).

=== "Strands MemoryStore"

    ```python
    import asyncio
    from strands.memory import MemoryManager
    from strands_postgres_store import PostgresMemoryStore
    from agentstate_reducer import MessageReducer, ReducerConfig, Background

    manager = MemoryManager(stores=[PostgresMemoryStore(name="memories", url=url)])

    def remember(pruned, namespace):                       # the reducer's on_prune hook
        for m in pruned:                                    # raw turns; add your own extraction call here if wanted
            asyncio.run(manager.add(m["content"], {"metadata": {"user": namespace, "role": m["role"]}}))

    reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))
    result = reducer.reduce(existing=agent.messages, namespace=session_id)   # Strands sessions do not run the reducer for you
    ```

    Strands' own `ModelExtractor` runs on the agent's live message path (via the store's `extraction` config), not on `MemoryManager.add`, so facts extracted from *pruned* turns need an explicit extraction call before `add`. Session managers do not invoke the reducer, so call `reduce()` yourself where you prune. See [Strands Memory Stores](../strands/memory.md).

=== "PydanticAI harness"

    ```python
    import asyncio
    from pydantic_ai_memory_core import append_memory
    from pydantic_ai_dynamodb_memory import DynamoDBMemoryStore
    from agentstate_reducer import MessageReducer, ReducerConfig, Background

    store = DynamoDBMemoryStore(table_name="agent-memory")

    def remember(pruned, namespace):                       # the reducer's on_prune hook
        text = "\n".join(f"- {m['content']}" for m in pruned)
        asyncio.run(append_memory(store, f"{namespace}/main/pruned.md", text))

    reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))
    ```

    The harness expects the **model** to write memory through `write_memory`; `append_memory` is a CAS-safe append that coexists with those writes, into a topic file the model can `read_memory` and `search_memory`. See [PydanticAI Memory Backends](../pydantic-ai/memory.md).

=== "Your own extractor"

    ```python
    def remember(pruned, namespace):                       # the reducer's on_prune hook
        facts = my_llm.extract(pruned)                     # any model, any prompt
        for fact in facts:
            store.put(namespace, key=str(uuid4()), value={"text": fact})

    reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))
    ```

=== "No extractor, raw turns (tested)"

    ```python
    def remember(pruned, namespace):                       # the reducer's on_prune hook
        for m in pruned:
            store.put(namespace, key=m.id, value={"role": m.type, "text": m.content})

    reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[remember]))   # cheap: inline
    ```

    Every LangGraph, CrewAI and Strands store embeds `text` on write when built with an index, so raw turns are still semantically searchable. Good enough to start; add an extractor later without changing anything else.

## Rules the hook follows

- Called with the pruned messages and the namespace the integration forwarded; `None` if it forwarded nothing.
- Each message id is delivered once per reducer instance, even across overlapping saves.
- A hook that raises is logged and skipped. The reduce, the checkpoint and the request all still succeed.
- `Background(fn)` runs the hook on a bounded pool and drops with a warning if the backlog fills. On serverless, call `close()` at the end of the handler.

Full reference: [Long-Term Memory Hooks](long-term-memory.md).
