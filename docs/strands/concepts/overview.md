# Overview

## Three concerns, kept separate

A Strands agent has three distinct persistence-adjacent concerns. This family handles **only the first**, on purpose:

| Concern | What it is | Owned by |
|---|---|---|
| **Session storage** | persist & restore this session's messages + agent state | **this family** (`session_manager=`) |
| **Pruning** | trim history to fit context / cost | a `ConversationManager` (`conversation_manager=`) |
| **Long-term memory** | cross-session facts, semantic recall | a memory tool (`tools=[...]`, e.g. Mem0) |

They plug into different `Agent` constructor slots and compose freely:

```python
Agent(
    session_manager=DynamoDBSessionManager(...),   # WHERE state is stored  ← this family
    conversation_manager=SlidingWindowConversationManager(...),  # HOW history is trimmed
    tools=[mem0_memory],                            # long-term memory
)
```

!!! warning "Why storage never prunes"
    Strands stores messages **individually, by index**, and restore replays them using `conversation_manager.removed_message_count` as an **offset** into that indexed list. If a storage backend silently dropped messages, the indices and offset math would break and restore would corrupt. So pruning stays a `ConversationManager` concern — never a storage one.

## How the family is structured

```
strands-agents-session (core)
    │  SessionStorage  (put / get / query / delete / delete_partition)
    │  KeyValueSessionManager  (implements the full Strands SessionRepository)
    │
    ├── strands-session-dynamodb   → DynamoDBSessionStorage
    ├── strands-session-mongodb    → MongoDBSessionStorage
    └── strands-session-sql        → SQLSessionStorage (SQLAlchemy)
```

- The **core** implements Strands' `SessionRepository` — all 8 CRUD methods — over a tiny `SessionStorage` interface, and mixes in `RepositorySessionManager`. So message indexing, restore, offsetting, and tool-use repair come from Strands unchanged.
- A **provider** implements just the `SessionStorage` interface (5 methods) for its database. That's the entire surface. See [Build Your Own Backend](../core/building-a-backend.md).

## What gets persisted

Passing a session manager to an `Agent` persists, keyed by `session_id` + `agent_id`:

- **Conversation messages** — one record per message, indexed
- **Agent state** — the `agent.state` key-value store
- **Conversation-manager state** — e.g. `removed_message_count`, so restore is correct

On the next run with the same `session_id`, all of it is restored automatically before the agent responds.

## Storage key layout

All backends use the same logical layout (keys are opaque strings, so any KV / range store fits):

| Item | pk | sk |
|---|---|---|
| Session | `SESSION#<session_id>` | `META` |
| Agent | `SESSION#<session_id>` | `AGENT#<agent_id>` |
| Message | `SESSION#<session_id>#AGENT#<agent_id>` | `MSG#<zero-padded id>` |

Message sort keys are zero-padded so lexical order equals numeric order — making `list_messages(offset, limit)` a simple ordered range scan that matches Strands' `removed_message_count` offset semantics.
