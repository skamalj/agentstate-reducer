# LangGraph Memory Engine — Extraction, Consolidation, Recall

[`langgraph-memory`](https://github.com/skamalj/langgraph-memory) fills the **extractor** column of the LangGraph row: it turns conversation into facts, keeps the set of facts converging instead of growing, and recalls them ranked by **semantic similarity, recency and importance**. It works over any `BaseStore` built with an `IndexConfig`, which means every [`langgraph-store-*`](stores.md) backend and LangGraph's own stores.

!!! note "Why it exists"
    LangMem, the only extraction engine in the LangGraph ecosystem, has been dormant since October 2025 and the LangGraph memory docs no longer mention it. This engine is a maintained alternative, modelled on CrewAI's unified `Memory` engine, which has the best-designed pipeline of the four frameworks.

```bash
pip install langgraph-memory
```

## Usage

```python
from langgraph_memory import MemoryEngine
from langgraph_store_postgres import PostgresStore
from langgraph_store_core import bedrock_titan_embeddings

store = PostgresStore(url, index={"dims": 1024, "embed": bedrock_titan_embeddings(dimensions=1024), "fields": ["content"]})
engine = MemoryEngine(store, "anthropic:claude-sonnet-5")

engine.remember(messages, namespace=("memories", "kamal"))                 # extract → dedupe → consolidate → put
for m in engine.recall("what does the user prefer for travel?", namespace=("memories", "kamal"), limit=5):
    print(m.score, m.record.content, m.match_reasons)
```

## The pipeline

| Stage | What happens |
|---|---|
| **Extract** | a chat model with structured output turns text or messages into discrete facts, each with categories and an importance in 0–1. Any name `init_chat_model` accepts, or a model instance, or your own `extractor` callable. |
| **Dedupe** | near-identical facts within one batch are collapsed |
| **Consolidate** | for each fact, `store.search(query=fact)` finds similar existing memories; at or above `consolidation_threshold` (0.85) the model decides **insert / update / skip**, so a corrected preference replaces the old one rather than sitting next to it |
| **Store** | one `BaseStore` item per memory: `content`, `categories`, `importance`, `created_at`, `last_accessed`, `source`, `private`, `metadata`. The store embeds `content` on `put`. |
| **Recall** | `store.search(query=...)` on the native vector engine, oversampled ×3, then re-ranked with CrewAI's formula and filtered |

### Recall parameters

```python
engine.recall(query, namespace, categories=["preference"], limit=5, min_score=0.4,
              source="session-42", include_private=False, filter={"metadata.team": "x"})
```

The composite score is `0.5 · similarity + 0.3 · recency_decay + 0.2 · importance` with `decay = 0.5 ^ (age_days / 30)`. Weights, half-life, thresholds and oversampling live in `MemoryConfig`. `match_reasons` says which components drove each hit. Recall bumps `last_accessed` with a metadata-only write that keeps the stored vector.

!!! tip "min_score is composite"
    A threshold tuned for the default weights changes meaning when the weights change, exactly as in CrewAI. Tune them together.

## Choosing the model

There is **no default model** — pass one explicitly. A memory engine that silently spends tokens on every prune would be a bad surprise, and the rest of the toolkit avoids picking a vendor for you. The embedding model is separate: it lives on the store's `IndexConfig`.

| Form | Example | Notes |
|---|---|---|
| Name string | `MemoryEngine(store, "anthropic:claude-sonnet-5")` | resolved by LangChain's `init_chat_model`; the provider package (`langchain-anthropic`, `langchain-aws`, `langchain-openai`, …) must be installed and configured |
| Model instance | `MemoryEngine(store, ChatBedrockConverse(model=..., region_name=...))` | any LangChain `BaseChatModel`; control temperature, region, timeouts, share a client |
| Callables, no model | `MemoryEngine(store, extractor=fn, consolidator=fn)` | `extractor(text) -> list[ExtractedFact]`, `consolidator(fact, similar) -> ConsolidationDecision`; how the tests run with zero LLM calls; mix with `model` for the other step |

The same model serves both LLM steps, extraction and the consolidation decision, and both use `with_structured_output`, so the model must support tool calling or JSON-schema output (current Anthropic, OpenAI, Bedrock Converse and Gemini chat models all do). The system prompts are overridable: `LLMExtractor(model, prompt=...)` and `LLMConsolidator(model, prompt=...)`, passed as `extractor=` / `consolidator=`, let you steer what counts as worth remembering for your domain without touching the pipeline.

## Integrations

=== "With the reducer's `on_prune` hook (tested)"

    ```python
    from agentstate_reducer import MessageReducer, ReducerConfig, Background
    from langgraph_dynamodb_checkpoint import DynamoDBSaver

    reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(engine.on_prune)]))
    saver = DynamoDBSaver("checkpoints", reducer=reducer)
    graph = builder.compile(checkpointer=saver, store=store)

    graph.invoke(input, config={"configurable": {"thread_id": tid, "memory_namespace": ("memories", user_id)}})
    ```

    `engine.on_prune` is a ready-made `RememberFn`: pruned turns are extracted and consolidated under the forwarded namespace. This is the shape of the e2e test that ships in the repo, on a real `DynamoDBSaver` and DynamoDB store.

=== "Agent tools"

    ```python
    agent = create_react_agent(model, tools=engine.tools())
    agent.invoke(input, config={"configurable": {"memory_namespace": ("memories", user_id)}})
    ```

    `search_memory(query)` and `manage_memory(content, action, key)` read the namespace from the run config, never from the model.

=== "Recall node"

    ```python
    graph.add_node("recall", engine.recall_node(into="memory", limit=5))
    graph.add_edge(START, "recall"); graph.add_edge("recall", "agent")
    ```

    Recalls for the last human message and writes formatted memories into `state["memory"]` for the prompt.

`engine.forget(namespace, key=... | categories=... | older_than=...)` and `engine.list(namespace)` for housekeeping; `aremember` / `arecall` for async graphs.

## Embedding

The engine never embeds anything. The store does, on `put` and on `search(query=...)`, with the `IndexConfig` it was built with, so one embedder serves writes, consolidation lookups and recall, and each backend uses its native vector engine. The constructor refuses a store without an `IndexConfig`. Dimensions are fixed at index creation on every backend; changing the embedding model means a new table and re-embedding.

## Testing

Offline and deterministic: LangGraph's `InMemoryStore` with `FakeEmbeddings` and rule-based extractor and consolidator callables in place of a model, 21 tests. The same assertions run against `langgraph-store-postgres` (pgvector) and `langgraph-store-dynamodb` (native `SearchVectors`), plus the full checkpointer → reducer → `on_prune` → engine → recall chain with a real graph.
