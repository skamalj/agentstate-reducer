# Strands Memory Store — DynamoDB

`strands-dynamodb-store` is a real Strands **`MemoryStore`** — long-term, semantic agent memory — backed by **DynamoDB's native vector search** (`SearchVectors`). No external vector database and no byte-`Storage` layer: it talks to DynamoDB directly, the way the SDK's `BedrockKnowledgeBaseStore` talks to Bedrock.

!!! note "Why not build on the Storage interface?"
    A `MemoryStore` needs `search(query) -> ranked entries`, but [`strands.storage.Storage`](storage.md) has **no search primitive** (only `write`/`read`/`delete`/`list`). So a semantic store can't ride generically on `Storage` — it must use a backend that *has* search. Here that's DynamoDB native vectors.

## Install

```bash
pip install strands-dynamodb-store
```

Requires **`boto3>=1.43.78`** (DynamoDB vector search, GA 2026-08-05), a region where it's available, and Bedrock model access for the default embedder.

## Usage

```python
from strands import Agent
from strands.memory import MemoryManager
from strands_dynamodb_store import DynamoDBMemoryStore

store = DynamoDBMemoryStore(name="user-memories", table_name="agent_memory")
agent = Agent(memory_manager=MemoryManager(stores=[store]))

# or directly:
await store.add("The user prefers dark mode", metadata={"kind": "pref"})
hits = await store.search("what theme does the user like?")
for h in hits:
    print(h.metadata["_score"], h.content)
```

## How it works

- **Semantic recall** via DynamoDB `search_vectors` (approximate nearest-neighbor over a vector index), ranked by similarity — at DynamoDB scale, no separate vector store.
- **You bring the embeddings.** DynamoDB does not generate them; by default the store embeds with **Amazon Bedrock Titan Text v2** (`amazon.titan-embed-text-v2:0`, 1024-dim, cosine). Pass any `embedder` callable for Cohere / OpenAI / local models.
- `add` stores an item `{id, content, embedding (List<Number>), metadata, createdAt}`; `search` embeds the query and runs the ANN search, surfacing the similarity `_score` in each entry's metadata.
- The table is auto-created if absent — `PAY_PER_REQUEST` with a vector index on the `embedding` attribute.

## Configuration

```python
DynamoDBMemoryStore(
    name, table_name, *,
    description=None, max_search_results=None, writable=True, extraction=None,
    embedder=None,                 # default: Bedrock Titan v2 (pluggable)
    dimensions=1024, distance_function="COSINE",
    index_name="vector_index", vector_attribute="embedding",
    region_name=None, boto_session=None, endpoint_url=None,
)
```

Implements the `MemoryStore` protocol: `search(query, options)` and `add(content, metadata)`.

!!! tip "Store vs. storage"
    `strands-dynamodb-store` (this page) is the semantic **memory** layer. For the byte **[Storage](storage.md)** backend use `strands-storage-dynamodb`. (`strands-dynamodb-store` 0.1.x was a storage alias; from 0.2.0 it is a `MemoryStore`.)

## License

MIT · part of the [strands-agents-session](https://github.com/skamalj/strands-agents-session) family.
