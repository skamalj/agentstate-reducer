# PydanticAI Memory Backends — Long-Term Memory (`MemoryStore`)

PydanticAI keeps its core small; everything that wraps a run lives in [`pydantic-ai-harness`](https://pydantic.dev/docs/ai/harness/memory/) as **capabilities** attached with `Agent(capabilities=[...])`. The harness's `Memory` capability (0.7+) gives an agent long-term memory as a **per-user Markdown notebook**: `MEMORY.md` is injected before every model call, and the model writes to it through `write_memory` / `read_memory` / `delete_memory` / `search_memory`. Underneath sits a pluggable **`MemoryStore`** protocol with compare-and-swap versions and idempotent operation receipts.

The [`pydantic-ai-memory`](https://github.com/skamalj/pydantic-ai-memory) family implements that protocol on managed cloud databases, so memory is shared and durable instead of a local directory.

!!! note "Memory vs. persistence"
    This is a different layer from [`pydantic-ai-persistence`](index.md). `StepPersistence` records **runs and messages** by conversation for resume; `Memory` keeps **what the model chose to remember** by user across conversations. The harness docs keep them as separate capabilities with separate stores, and so do we.

## Packages

| Package | Backend | CAS mechanism |
|---|---|---|
| [`pydantic-ai-memory-core`](https://pypi.org/project/pydantic-ai-memory-core/) | shared base — build your own with 9 conditional primitives | — |
| [`pydantic-ai-dynamodb-memory`](https://pypi.org/project/pydantic-ai-dynamodb-memory/) | Amazon DynamoDB | conditional writes |
| [`pydantic-ai-cosmosdb-memory`](https://pypi.org/project/pydantic-ai-cosmosdb-memory/) | Azure Cosmos DB (NoSQL) | `create_item` + ETag `If-Match` |
| [`pydantic-ai-firestore-memory`](https://pypi.org/project/pydantic-ai-firestore-memory/) | Google Firestore | transactions |
| [`pydantic-ai-postgres-memory`](https://pypi.org/project/pydantic-ai-postgres-memory/) | PostgreSQL | upstream `PostgresMemoryStore`, built from a URL |

```bash
pip install pydantic-ai-dynamodb-memory     # or -cosmosdb- / -firestore- / -postgres-
```

## Usage

```python
from dataclasses import dataclass
from pydantic_ai import Agent
from pydantic_ai_harness.memory import Memory
from pydantic_ai_dynamodb_memory import DynamoDBMemoryStore   # or CosmosDBMemoryStore / FirestoreMemoryStore / PostgresMemoryStoreFromUrl

@dataclass
class Deps:
    user_id: str

store = DynamoDBMemoryStore(table_name="agent-memory")
agent = Agent("anthropic:claude-sonnet-5", deps_type=Deps,
              capabilities=[Memory(store=store, namespace=lambda ctx: ctx.deps.user_id)])

agent.run_sync("I moved to Hanoi and hate early flights.", deps=Deps("kamal"))   # the model calls write_memory
agent.run_sync("Book me something to Bangkok.", deps=Deps("kamal"))              # kamal/main/MEMORY.md injected first
```

Nothing in the agent changes when you swap the store. The namespace is resolved once per run from `deps`, never exposed as a tool argument.

## What a backend must guarantee

The harness contract, from its docs: versions are opaque strings used for optimistic compare-and-swap; a write or delete with a stale `expected_version` raises `MemoryConflictError` instead of overwriting; `MemoryOperation` receipts make mutations idempotent under durable-execution replay and must be implemented atomically; every `read` has a finite `max_chars`. `pydantic-ai-memory-core` implements all of it over nine conditional primitives:

| Primitive | Meaning |
|---|---|
| `_get_file`, `_list_paths` | read a file row; sorted paths under a prefix |
| `_create_file` | write only if absent |
| `_replace_file`, `_delete_file` | write or delete only if the stored version matches |
| `_get_receipt`, `_reserve_receipt`, `_complete_receipt`, `_drop_receipt` | operation receipt lifecycle |

Each must be atomic in the backend, which is what the CAS column in the table above names.

=== "DynamoDB"

    One table, `pk` = `f#<path>` for files and `o#<operation id>` for receipts. Create uses `attribute_not_exists(pk)`; replace and delete require `version = :expected`. Auto-created, `PAY_PER_REQUEST`.

=== "Cosmos DB"

    One container partitioned by `/id`. Create uses `create_item`; replace and delete re-read, check the harness version, then write with `If-Match` on the Cosmos ETag.

=== "Firestore"

    One collection. Create, replace and delete each run in a Firestore transaction that reads, checks the version, then writes. No index setup: receipts carry no `path` field, so the prefix listing is a single-field range.

=== "PostgreSQL"

    Delegates to the harness's own transactional `PostgresMemoryStore`; the package just builds it from a URL and keeps one asyncpg pool per event loop, since agents are usually driven from several loops.

## Search

`search_memory` uses the harness's bounded **lexical** search on every backend (`SearchableMemoryStore`), the same as the upstream stores. Semantic ranking is explicitly not built into the harness; a vector-ranked `search` over file chunks is the natural next step for these backends.

## With `on_prune`

The harness expects the **model** to write memory. To also feed memory from the [reducer's `on_prune` hook](../reducer/long-term-memory.md), use `append_memory` from the core, a CAS-safe append with retries that coexists with the model's own writes:

```python
import asyncio
from agentstate_reducer import Background
from pydantic_ai_memory_core import append_memory

def remember(pruned, namespace):
    text = "\n".join(f"- {m['content']}" for m in pruned)
    asyncio.run(append_memory(store, f"{namespace}/main/pruned.md", text))

reducer = MessageReducer(config=ReducerConfig(max_messages=20, on_prune=[Background(remember)]))
```

The topic file `pruned.md` is listed to the model alongside `MEMORY.md` and is reachable through `read_memory` and `search_memory`.

## Testing

`pydantic_ai_memory_core.contract` is one importable suite every provider runs against its real backend: CAS conflicts, receipt replay and fingerprint conflicts, rollback on failure, prefix listing, bounded search, concurrent appends, and an end-to-end pass through the real `Memory` capability on a PydanticAI `Agent` driven by a scripted `FunctionModel`, with no LLM.

!!! warning "Harness is 0.x"
    `pydantic-ai-harness` carries an Alpha classifier and may change between minor releases. The `MemoryStore` surface has been stable since 0.7.0; pin by minor version and watch release notes.
