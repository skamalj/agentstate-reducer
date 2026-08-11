# Core — What You Get

`strands-agents-session` is the backend-agnostic core of the family. Install it directly only if you're using the in-memory backend or building your own; most users install a provider (which pulls the core automatically).

```bash
pip install strands-agents-session
```

## What's in the box

| Component | What it does |
|---|---|
| **`KeyValueSessionManager`** | Implements the **full Strands `SessionRepository`** (all 8 CRUD methods) over a `SessionStorage`, and mixes in `RepositorySessionManager`. You get message indexing, restore, `removed_message_count` offsetting, tool-use repair, and change detection — unchanged from Strands. |
| **`SessionStorage`** | The tiny interface a backend implements: `put` / `get` / `query` / `delete` / `delete_partition`. |
| **`InMemorySessionStorage`** | A ready in-memory backend — great for tests and local development. |
| **`keys`** | Shared key/serialization conventions (zero-padded message sort keys for ordered range scans). |

## Using the in-memory backend

```python
from strands import Agent
from strands_agents_session import KeyValueSessionManager, InMemorySessionStorage

session_manager = KeyValueSessionManager(
    session_id="user-123",
    storage=InMemorySessionStorage(),
)
agent = Agent(session_manager=session_manager)
```

!!! note
    `InMemorySessionStorage` is not persistent across processes — it's for tests, prototyping, and as a reference implementation. For durability use [DynamoDB](../providers/dynamodb.md), [MongoDB](../providers/mongodb.md), [SQL](../providers/sql.md), or [your own backend](building-a-backend.md).

## What the core does NOT do

- **It does not prune.** Pruning is a `ConversationManager` concern (see [Overview](../concepts/overview.md)).
- **It does not import your database.** The core is storage-agnostic — a provider supplies the storage.
- **It does not require you to touch Strands types.** When you build a backend, you move opaque dict records; all Strands typing and restore logic stays in the core.

Ready to build a backend? → **[Build Your Own Backend](building-a-backend.md)**
