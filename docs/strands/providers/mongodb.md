# MongoDB Provider

`strands-session-mongodb` is a MongoDB storage backend for [Strands Agents](https://strandsagents.com). It persists an agent's sessions, agent state, conversation-manager state, and messages to MongoDB so conversations resume across runs. It implements the core [`SessionStorage`](../core/index.md) interface, so all the Strands session-repository logic — message indexing, restore, `removed_message_count` offsetting, tool-use repair — comes from the core.

!!! info "Storage only, by design"
    Message *pruning* in Strands is a `ConversationManager` concern, decoupled from storage. This package does **not** prune.

## Installation

Requires **Python 3.10+** and a reachable MongoDB (local, Atlas, or self-hosted).

=== "Standalone"

    ```bash
    pip install strands-session-mongodb
    ```

=== "Family extra"

    ```bash
    pip install "strands-agents-session[mongodb]"
    ```

## Quick start

```python
from strands import Agent
from strands_session_mongodb import MongoDBSessionManager

session_manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://127.0.0.1:27017/",
)

agent = Agent(session_manager=session_manager)
agent("Hi, I'm Kamal")
agent("What's my name?")   # remembers within the session
```

Next run, same `session_id` → the agent restores its full history and state from MongoDB.

## Constructor parameters

`MongoDBSessionManager(session_id, *, connection_string="mongodb://127.0.0.1:27017/", database_name="strands_sessions", collection_name="sessions", client=None, ttl_seconds=None)`

| Parameter | Description |
|---|---|
| `session_id` | Session identifier |
| `connection_string` | MongoDB URI (local, Atlas `mongodb+srv://…`, etc.) |
| `database_name` | Database (default `strands_sessions`) |
| `collection_name` | Collection (default `sessions`) |
| `client` | Optional pre-built `pymongo.MongoClient` to reuse |
| `ttl_seconds` | If set, adds a TTL index so documents expire automatically |

For connection strings and the full auth surface (SCRAM, TLS, Atlas SRV, X.509, AWS IAM), see [Authentication](../concepts/auth.md).

## Data model

A single collection; each document has a `pk` + `sk` (compound-indexed, **unique**) and a `data` field with the serialized payload:

| Item | pk | sk |
|---|---|---|
| Session | `SESSION#<session_id>` | `META` |
| Agent | `SESSION#<session_id>` | `AGENT#<agent_id>` |
| Message | `SESSION#<session_id>#AGENT#<agent_id>` | `MSG#<zero-padded id>` |

The `(pk, sk)` index gives ordered range scans, so `list_messages(offset, limit)` is a simple indexed `find(...).sort(sk).limit(...)` — matching the `removed_message_count` offset semantics Strands relies on.

!!! note "Same key layout as DynamoDB"
    The `pk`/`sk` layout is identical to the [DynamoDB provider](dynamodb.md). Both providers share the core storage contract; only the underlying store differs.

## See also

- [What You Get](../core/index.md) — the shared `SessionStorage` contract this provider implements.
- [Build Your Own Backend](../core/building-a-backend.md) — write a storage backend of your own.
- [Authentication](../concepts/auth.md) — the full pymongo/URI auth surface.

---

*Version 0.1.0 · MIT License*
