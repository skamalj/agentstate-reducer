# Strands Memory Stores

Real Strands **`MemoryStore`** implementations — long-term, *semantic* agent memory (`search` / `add`) — each backed by its datastore's **native vector search**. No external vector database.

!!! note "Why native vector search (not the Storage interface)?"
    A `MemoryStore` needs `search(query) -> ranked entries`, but [`strands.storage.Storage`](storage.md) has **no search primitive** (only `write`/`read`/`delete`/`list`). So a semantic store can't ride generically on `Storage` — it must use a backend that *has* search. Each store below talks to its backend directly, the way the SDK's `BedrockKnowledgeBaseStore` talks to Bedrock.

## The stores

| Package | Vector engine | Backend requirement |
|---|---|---|
| [`strands-dynamodb-store`](https://pypi.org/project/strands-dynamodb-store/) | DynamoDB native **`SearchVectors`** | `boto3>=1.43.78` |
| [`strands-postgres-store`](https://pypi.org/project/strands-postgres-store/) · `strands-store-postgres` | PostgreSQL **pgvector** (`<=>` / HNSW) | `vector` extension on the server |
| [`strands-mongodb-store`](https://pypi.org/project/strands-mongodb-store/) · `strands-store-mongodb` | MongoDB **Atlas `$vectorSearch`** | MongoDB **Atlas** |

## Usage

```python
from strands import Agent
from strands.memory import MemoryManager
from strands_postgres_store import PostgresMemoryStore   # or DynamoDBMemoryStore / MongoDBMemoryStore

store = PostgresMemoryStore(name="user-memories", url="postgresql://user:pass@host:5432/db")
agent = Agent(memory_manager=MemoryManager(stores=[store]))

await store.add("The user prefers dark mode", metadata={"kind": "pref"})
hits = await store.search("what theme does the user like?")
for h in hits:
    print(h.metadata["_score"], h.content)
```

Constructor per backend:

=== "DynamoDB"

    ```python
    from strands_dynamodb_store import DynamoDBMemoryStore
    DynamoDBMemoryStore(name="mem", table_name="agent_memory")   # native SearchVectors
    ```

=== "PostgreSQL (pgvector)"

    ```python
    from strands_postgres_store import PostgresMemoryStore
    PostgresMemoryStore(name="mem", url="postgresql://user:pass@host:5432/db")
    ```

=== "MongoDB (Atlas)"

    ```python
    from strands_mongodb_store import MongoDBMemoryStore
    MongoDBMemoryStore(name="mem",
        connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
        database_name="agent", collection_name="memory")
    ```

## How it works

- **Semantic recall** via the backend's native ANN — ranked by similarity, surfaced as `_score` in each entry's metadata.
- **You bring the embeddings.** None of these backends generate them; by default each store embeds with **Amazon Bedrock Titan Text v2** (1024-dim, cosine). Pass any `embedder` callable (`Callable[[str], list[float]]`) to use Cohere / OpenAI / a local model.
- Each `add` stores `{id, content, embedding, metadata, createdAt}`; the table / index (DynamoDB vector index, pgvector HNSW, Atlas vector index) is created automatically.

!!! tip "Store vs. storage"
    A memory **store** (`strands-<backend>-store`) is the *semantic* layer. The byte **[Storage](storage.md)** backend is `strands-<backend>-storage` / `strands-storage-<backend>` — a different, lower layer.

## Backend notes

- **DynamoDB** — native vector search GA'd 2026-08-05; needs a region where it's available. Table is `PAY_PER_REQUEST` with a vector index.
- **PostgreSQL** — needs the `pgvector` extension (`apt install postgresql-16-pgvector`, `brew install pgvector`, or the extension on RDS / Cloud SQL / Azure). The store runs `CREATE EXTENSION IF NOT EXISTS vector`.
- **MongoDB** — Atlas only (`$vectorSearch` is an Atlas feature); community/self-hosted MongoDB is not supported.

## License

MIT · part of the [strands-agents-session](https://github.com/skamalj/strands-agents-session) family.
