# Build Your Own Backend

Adding a storage backend is intentionally small: implement the **`SessionStorage`** interface (5 methods) and wrap it in a `KeyValueSessionManager`. Everything else — the full Strands `SessionRepository`, message indexing, restore, pagination, offsetting, tool-use repair — comes from the core.

## The mental model

Your backend **never imports Strands types and never parses payloads.** It's a plain ordered keyed-record store that moves opaque dicts:

```
KeyValueSessionManager  (core: knows Strands, does all serialization)
        │  passes/receives records: {"pk": str, "sk": str, "data": str}
        ▼
   SessionStorage  (you: just persist and return those records)
        ▼
   your database
```

- `pk` / `sk` are **opaque strings** — treat them as identifiers; never parse them.
- `data` is an **opaque serialized string** — store and return it **verbatim**; never inspect or modify it.

That's the whole reason a backend is ~30 lines: all the Strands knowledge lives in the core.

## The record

Every method deals in a single record shape:

```python
{"pk": "SESSION#user-123", "sk": "META", "data": "<opaque serialized string>"}
```

## The contract

Implement these five methods. **Semantics matter** — the core relies on them:

| Method | Signature | Must do | Returns |
|---|---|---|---|
| `put` | `put(item: dict) -> None` | **Upsert** the record by `(pk, sk)` — insert or overwrite | `None` |
| `get` | `get(pk: str, sk: str) -> dict \| None` | Fetch one record | The record dict, or **`None`** if absent |
| `query` | `query(pk: str, sk_gte: str \| None = None, limit: int \| None = None) -> list[dict]` | Records under `pk`, **ordered by `sk` ascending**; if `sk_gte` given, only `sk >= sk_gte` (**inclusive**); if `limit` given, at most that many | List of record dicts (**`[]`** if none) |
| `delete` | `delete(pk: str, sk: str) -> None` | Delete one record if present — **idempotent** (no error if missing) | `None` |
| `delete_partition` | `delete_partition(pk: str) -> None` | Delete **all** records under `pk` — idempotent | `None` |

!!! warning "Ordering is load-bearing"
    `query` **must** return records sorted by `sk` ascending. Message sort keys are zero-padded (`MSG#00000000000000000007`) so lexical order equals numeric order — this is what makes `list_messages(offset, limit)` correct. If your store sorts differently, sort explicitly.

Notes:
- `get`/`query` return records in the **same `{pk, sk, data}` shape**.
- `put` is an **upsert**, not insert — the core calls it for both creates and updates (e.g. message redaction).
- Duplicate-session detection, "does this agent exist", timestamp preservation, etc. are handled **by the core** on top of these primitives — you don't implement them.

## Worked example — a SQLite backend

A complete, runnable backend in ~30 lines using Python's built-in `sqlite3`:

```python
import sqlite3
from strands_agents_session import KeyValueSessionManager, SessionStorage


class SQLiteSessionStorage(SessionStorage):
    def __init__(self, path: str = "sessions.db"):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  pk TEXT NOT NULL, sk TEXT NOT NULL, data TEXT NOT NULL,"
            "  PRIMARY KEY (pk, sk))"
        )
        self.conn.commit()

    def put(self, item):
        self.conn.execute(
            "INSERT INTO sessions (pk, sk, data) VALUES (?, ?, ?) "
            "ON CONFLICT(pk, sk) DO UPDATE SET data = excluded.data",
            (item["pk"], item["sk"], item["data"]),
        )
        self.conn.commit()

    def get(self, pk, sk):
        row = self.conn.execute(
            "SELECT data FROM sessions WHERE pk = ? AND sk = ?", (pk, sk)
        ).fetchone()
        return {"pk": pk, "sk": sk, "data": row[0]} if row else None

    def query(self, pk, sk_gte=None, limit=None):
        sql = "SELECT sk, data FROM sessions WHERE pk = ?"
        params = [pk]
        if sk_gte is not None:
            sql += " AND sk >= ?"
            params.append(sk_gte)
        sql += " ORDER BY sk ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [{"pk": pk, "sk": sk, "data": data}
                for sk, data in self.conn.execute(sql, params).fetchall()]

    def delete(self, pk, sk):
        self.conn.execute("DELETE FROM sessions WHERE pk = ? AND sk = ?", (pk, sk))
        self.conn.commit()

    def delete_partition(self, pk):
        self.conn.execute("DELETE FROM sessions WHERE pk = ?", (pk,))
        self.conn.commit()


class SQLiteSessionManager(KeyValueSessionManager):
    def __init__(self, session_id, path="sessions.db"):
        super().__init__(session_id=session_id, storage=SQLiteSessionStorage(path))
```

Use it exactly like any provider:

```python
from strands import Agent

agent = Agent(session_manager=SQLiteSessionManager(
    session_id="user-123", path="sessions.db",
))
agent("Hi, I'm Kamal")
```

!!! tip "This is essentially the SQL provider"
    The official [`strands-session-sql`](../providers/sql.md) provider is this idea generalized over SQLAlchemy so one backend covers SQLite, Postgres, and MySQL. If you only need SQLite, the snippet above is all it takes.

## Backend responsibilities (not the core's)

The core stays storage-neutral, so these are yours to decide per backend:

- **Indexing** — ensure `(pk, sk)` lookups and ordered `sk` range scans are efficient (a composite index / primary key).
- **TTL / expiry** — if you want automatic session expiry, add it in your storage (e.g. a TTL index / column). It's optional.
- **Concurrency / connections** — connection pooling and thread-safety are the backend's concern.
- **Serialization** — none. The core serializes to the `data` string; you store it as-is.

## Testing your backend

Point the existing test shape at your manager — build a session, create agents/messages, and assert round-trips, ordering, offset/limit, redaction, and isolation. For a zero-dependency reference, the core's `InMemorySessionStorage` and its test suite show the exact expectations every backend must satisfy.
