# LangGraph Stores — Long-Term Memory (`BaseStore`)

LangGraph keeps **short-term** state in a checkpointer (one thread) and **long-term** memory in a `BaseStore` (shared across threads, keyed by namespace). The [`langgraph-store`](https://github.com/skamalj/langgraph-store) family provides `BaseStore` backends on managed cloud databases — with prefix search, Mongo-style filters, `list_namespaces`, sync + async, and **native semantic search**.

!!! success "Semantic search on every backend"
    Pass LangGraph's `IndexConfig` and each store embeds values on `put` and ranks `search(query=...)` by cosine similarity using its backend's **own** vector engine — DynamoDB `SearchVectors`, pgvector, Cosmos `VectorDistance`, Firestore `find_nearest`. No external vector database. This is the store side of the [`on_prune` long-term-memory hooks](../reducer/long-term-memory.md) and of LangMem's semantic tools.

## Packages

| Package | Backend | Semantic search via |
|---|---|---|
| [`langgraph-store-core`](https://pypi.org/project/langgraph-store-core/) | shared base — build your own with 4 primitives | portable cosine fallback |
| [`langgraph-store-dynamodb`](https://pypi.org/project/langgraph-store-dynamodb/) | Amazon DynamoDB | native vector search (`SearchVectors`) |
| [`langgraph-store-postgres`](https://pypi.org/project/langgraph-store-postgres/) | PostgreSQL | pgvector (`<=>`, HNSW) |
| [`langgraph-store-cosmosdb`](https://pypi.org/project/langgraph-store-cosmosdb/) | Azure Cosmos DB (NoSQL) | `VectorDistance` (diskANN) |
| [`langgraph-store-firestore`](https://pypi.org/project/langgraph-store-firestore/) | Google Firestore | `find_nearest` (vector index) |

```bash
pip install langgraph-store-dynamodb     # or -postgres / -cosmosdb / -firestore
```

## Key/value memory

```python
from langgraph_store_postgres import PostgresStore   # or DynamoDBStore / CosmosDBStore / FirestoreStore

store = PostgresStore("postgresql://user:pass@localhost:5432/db")

store.put(("users", "1", "memories"), "food", {"text": "loves sushi", "kind": "pref"})
item = store.get(("users", "1", "memories"), "food")
hits = store.search(("users", "1"), filter={"kind": "pref"}, limit=10)     # prefix + filter
spaces = store.list_namespaces(prefix=("users",))

graph = builder.compile(checkpointer=saver, store=store)                    # as a LangGraph store
```

Filters support `$eq` / `$ne` / `$gt` / `$gte` / `$lt` / `$lte` / `$in` / `$nin`; `list_namespaces` supports prefix, suffix, wildcards and `max_depth`.

## Semantic search

```python
from langgraph_store_core import bedrock_titan_embeddings
from langgraph_store_dynamodb import DynamoDBStore

store = DynamoDBStore("langgraph-memory",
    index={"dims": 1024, "embed": bedrock_titan_embeddings(dimensions=1024), "fields": ["text"]})

store.put(("memories", "kamal"), "k1", {"text": "the user loves sushi", "kind": "pref"})
hits = store.search(("memories", "kamal"), query="what food does the user like?", filter={"kind": "pref"})
print(hits[0].score, hits[0].value)
```

- **`embed`** — any LangChain `Embeddings`, a `list[str] -> list[list[float]]` callable, or a provider string such as `"openai:text-embedding-3-small"`. `bedrock_titan_embeddings()` ships in core.
- **`fields`** — JSON paths to embed; default `["$"]` (the whole value). `put(..., index=False)` skips one item; `put(..., index=["title"])` overrides the fields.
- **`score`** — cosine similarity on every `SearchItem` when `query` is given; `None` otherwise.
- A store constructed **without** `index` is filter-only and ignores `query`, exactly as LangGraph documents. **LangMem never passes `index=` itself**, so pair it only with a store built with an `IndexConfig`, or its semantic search silently degrades to filter-only.

=== "DynamoDB"

    Table is created with a vector index (`embedding`, cosine, `dims`, `PK` as inline filter). A vector index can only be declared at table creation — use a **new table** when enabling semantic search. Prefix search runs one ANN query per namespace under the prefix (DynamoDB only allows equality on string search-schema attributes); value filters are applied on the candidates. `boto3>=1.43.78`, region with vector search.

=== "PostgreSQL"

    Needs the `pgvector` extension; the store runs `CREATE EXTENSION IF NOT EXISTS vector`, adds `embedding vector(dims)` and an HNSW cosine index. Prefix and equality filters run in SQL (JSONB containment).

=== "Cosmos DB"

    Container is created with a vector embedding policy on `/embedding` and a `diskANN` index — use a **new container** when enabling. The account needs the `EnableNoSQLVectorSearch` capability. Prefix and equality filters run in the query.

=== "Firestore"

    Needs a composite vector index `prefix ASC + embedding (flat)`; the store creates it via the Admin API (`create_index=True`, asynchronous build — queries fail with `FAILED_PRECONDITION` until READY). Prefix is a range pre-filter; value filters are applied on the candidates.

## With `on_prune`

```python
def remember(pruned, namespace):
    for m in pruned:
        store.put(tuple(namespace), key=str(uuid4()), value={"role": m.type, "text": m.content})

reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[remember]))
saver = DynamoDBSaver("checkpoints", reducer=reducer)
graph = builder.compile(checkpointer=saver, store=store)
# later, anywhere:
store.search(("memories", user_id), query="what did the user say about travel?")
```

Because `text` is an indexed field, every pruned turn becomes semantically searchable long-term memory the moment it leaves the window. See [Long-Term Memory Hooks](../reducer/long-term-memory.md).

## Building your own backend

Subclass `langgraph_store_core.KVStore` and implement `_read`, `_write`, `_remove`, `_scan`; optionally `_vector_search(prefix, vector, filter, limit) -> [(row, score)]` for native ANN. Everything else — `batch`/`abatch`, timestamps, filters, namespace matching, embedding on put, scoring — is inherited. `langgraph_store_core.testing.FakeEmbeddings` is a deterministic embedder for tests.
