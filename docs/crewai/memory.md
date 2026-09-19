# CrewAI Memory Backends — Long-Term Memory (`StorageBackend`)

CrewAI 1.10+ has one unified **`Memory`** engine: it extracts facts from task outputs, infers a hierarchical scope and categories with an LLM, consolidates near-duplicates, and ranks recall by a composite of semantic similarity, recency decay and importance. Underneath sits a pluggable **`StorageBackend`** protocol, and the built-in store is LanceDB on local disk.

The [`crewai-memory`](https://github.com/skamalj/crewai-memory) family provides `StorageBackend` implementations on managed cloud databases, each using its backend's **native vector search**. CrewAI's engine keeps doing all the thinking; the backend just becomes shared and durable.

!!! note "Memory vs. Flow persistence"
    This is a different layer from the [`crewai-persistence-*`](dynamodb.md) packages. Flow persistence snapshots the **whole state of one flow run** for resume/fork; memory stores **discrete facts** for cross-run retrieval. CrewAI's docs keep them separate, and so do we.

## Packages

| Package | Backend | Vector search via |
|---|---|---|
| [`crewai-memory-core`](https://pypi.org/project/crewai-memory-core/) | shared base — build your own with 5 primitives | portable cosine fallback |
| [`crewai-memory-dynamodb`](https://pypi.org/project/crewai-memory-dynamodb/) | Amazon DynamoDB | native `SearchVectors` |
| [`crewai-memory-postgres`](https://pypi.org/project/crewai-memory-postgres/) | PostgreSQL | pgvector (`<=>`, HNSW) |
| [`crewai-memory-cosmosdb`](https://pypi.org/project/crewai-memory-cosmosdb/) | Azure Cosmos DB (NoSQL) | `VectorDistance` (diskANN) |
| [`crewai-memory-firestore`](https://pypi.org/project/crewai-memory-firestore/) | Google Firestore | `find_nearest` (vector index) |

```bash
pip install crewai-memory-dynamodb     # or -postgres / -cosmosdb / -firestore
```

## Usage

```python
from crewai import Crew
from crewai.memory import Memory
from crewai_memory_dynamodb import DynamoDBMemoryBackend   # or PostgresMemoryBackend / CosmosDBMemoryBackend / FirestoreMemoryBackend

backend = DynamoDBMemoryBackend(table_name="crewai-memory", dimensions=3072)   # match the Memory embedder
memory = Memory(storage=backend)
crew = Crew(agents=[...], tasks=[...], memory=memory)

memory.remember("The customer prefers email over phone", scope="/customers/acme", categories=["preference"])
matches = memory.recall("how should we contact acme?", scope="/customers")
```

Register once for every `Crew(memory=True)` instead:

```python
from crewai.memory.storage.factory import set_memory_storage_factory
set_memory_storage_factory(lambda spec: DynamoDBMemoryBackend("crewai-memory", dimensions=3072))
```

Agents then `recall` before each task and `remember` extracted facts after each run automatically.

## What a backend must do

The protocol has fifteen methods, but they collapse into four capabilities, all handled by `crewai-memory-core` over five primitives (`_put`, `_get`, `_delete_ids`, `_scan`, optional `_vector_search`):

| Capability | Methods | How the core does it |
|---|---|---|
| Filtered vector search | `search`, `asearch` | provider's native ANN in the scope subtree, then `categories` / `metadata_filter` / `min_score` on the candidates |
| Point read/write | `save`, `update`, `get_record`, `touch_records` | `_put` / `_get` |
| Filtered scan & delete | `list_records`, `delete`, `count`, `reset` | `_scan` + Python filters (`older_than`, categories, metadata) |
| Scope introspection | `get_scope_info`, `list_scopes`, `list_categories` | `_scan` + path arithmetic |

Scope prefixes are path-aware: `/a` matches `/a` and `/a/...`, never `/ab`.

=== "DynamoDB"

    Table `PK` = scope, `SK` = id, a `by_id` GSI, and a vector index on `embedding` with `PK` as an inline filter. DynamoDB allows only equality on a string search-schema attribute, so a subtree search runs one `SearchVectors` per concrete scope and merges by similarity (`1 - distance`). Vector index fixed at creation; `boto3>=1.43.78`.

=== "PostgreSQL"

    One table with `embedding vector(dims)`, HNSW cosine index, B-tree on `scope`. Search is a single `ORDER BY embedding <=> query` with `scope = p OR scope LIKE 'p/%'`. Needs the `pgvector` extension.

=== "Cosmos DB"

    Container partitioned by `/scope`, vector embedding policy on `/embedding` + `diskANN` index. Search is one SQL query ordered by `VectorDistance`. Needs the `EnableNoSQLVectorSearch` account capability; policy fixed at container creation.

=== "Firestore"

    One collection, embedding stored as a `Vector`, composite index `scope ASC + embedding (flat)` created via the Admin API (asynchronous). A subtree search is two `find_nearest` calls (exact scope + `scope/…` range) merged by similarity; root searches use the `scope >= "/"` range so one index serves everything.

## Testing

`crewai_memory_core.contract` is one importable suite that every provider runs against its real backend, including an end-to-end pass through CrewAI's `Memory` engine with `FakeEmbedder` and **zero LLM calls** (all record fields supplied → fast-path insert; `consolidation_threshold=1.0`; `recall(depth="shallow")`).

## With `on_prune`

When flow state carries a `messages` list pruned by our [`crewai-persistence-*`](dynamodb.md) packages, the reducer's [`on_prune` hook](../reducer/long-term-memory.md) can feed the pruned turns straight into this memory:

```python
from agentstate_reducer import Background

def remember(pruned, namespace):
    text = "\n".join(m["content"] for m in pruned)
    memory.remember_many(memory.extract_memories(text), scope=namespace)   # two LLM calls → run off-path

reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))
```

Here the `namespace` is a CrewAI scope path string (for example `/flow/<id>` or `/user/kamal`).
