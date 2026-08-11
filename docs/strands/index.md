# Strands Agents Session

Pluggable **session storage** for [Strands Agents](https://strandsagents.com) — persist an agent's sessions, agent state, and messages so conversations resume across runs. A backend-agnostic core plus swappable storage providers.

## The family

| Package | Backend | Install |
|---|---|---|
| [`strands-agents-session`](core/index.md) | core (interface + in-memory) | `pip install strands-agents-session` |
| [`strands-session-dynamodb`](providers/dynamodb.md) | Amazon DynamoDB | `pip install "strands-agents-session[dynamodb]"` |
| [`strands-session-mongodb`](providers/mongodb.md) | MongoDB | `pip install "strands-agents-session[mongodb]"` |
| [`strands-session-sql`](providers/sql.md) | SQL via SQLAlchemy (Postgres, SQLite, MySQL) | `pip install "strands-agents-session[sql]"` |

Each provider is an independent PyPI package that pulls the core transitively — a DynamoDB user never installs Mongo code. Pick one directly, or via the core's extras.

## Quick taste

```python
from strands import Agent
from strands_session_dynamodb import DynamoDBSessionManager

agent = Agent(session_manager=DynamoDBSessionManager(
    session_id="user-123", table_name="strands-sessions",
))

agent("Hi, I'm Kamal")
agent("What's my name?")   # remembers within the session
```

Next run with the same `session_id` → the agent restores its full history and state.

## Why this exists

Strands ships `FileSessionManager` and `S3SessionManager`. This family adds **more backends** — DynamoDB (cheaper/faster than S3 for small frequent session items), MongoDB, and any SQL database — behind one consistent interface, and makes **writing your own backend** a ~30-line job.

## Design in one line

The **core** implements Strands' full `SessionRepository` over a tiny `SessionStorage` interface; a **provider** just implements that interface for its database. See [Overview](concepts/overview.md) and [Build Your Own Backend](core/building-a-backend.md).

!!! note "Storage only, by design"
    Message *pruning* in Strands is a `ConversationManager` concern, deliberately decoupled from storage. These packages never prune — doing so at the storage layer would corrupt Strands' message-index/offset restore logic.

## Where to start

- New here? Read the **[Overview](concepts/overview.md)**.
- Want a specific backend? Jump to [DynamoDB](providers/dynamodb.md), [MongoDB](providers/mongodb.md), or [SQL](providers/sql.md).
- Building your own? **[Build Your Own Backend](core/building-a-backend.md)**.
