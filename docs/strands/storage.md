# Strands Storage Backends

Community implementations of Strands' unified **`strands.storage.Storage`** interface — durable **bytes-under-keys** that back session snapshots, context offloading, memory stores, and anything else in the SDK that needs key/value persistence. This is a *different, lower layer* than the [session managers](index.md): `Storage` is `write` / `read` / `delete` / `list`, with no notion of sessions or messages.

!!! note "Storage vs. session vs. memory"
    - **[Session managers](index.md)** (`strands-session-*`) implement `SessionRepository` — sessions, agent state, messages.
    - **Storage backends** (this page) implement `strands.storage.Storage` — opaque bytes.
    - **[Memory store](memory.md)** (`strands-dynamodb-store`) implements `MemoryStore` — semantic recall.

## The interface

```python
class Storage(Protocol):
    async def write(self, key: str, data: bytes) -> None
    async def read(self, key: str) -> bytes | None
    async def delete(self, key: str) -> None
    async def list(self, prefix: str) -> list[str]   # full keys, sorted
```

## The backends

| Package | Backend | Install |
|---|---|---|
| [`strands-sql-storage`](https://pypi.org/project/strands-sql-storage/) | any SQLAlchemy DB | `pip install strands-sql-storage` |
| [`strands-postgres-storage`](https://pypi.org/project/strands-postgres-storage/) · `strands-storage-postgres` | PostgreSQL | `pip install strands-postgres-storage` |
| [`strands-mongodb-storage`](https://pypi.org/project/strands-mongodb-storage/) · `strands-storage-mongodb` | MongoDB | `pip install strands-mongodb-storage` |
| [`strands-storage-dynamodb`](https://pypi.org/project/strands-storage-dynamodb/) | Amazon DynamoDB | `pip install strands-storage-dynamodb` |

Each backend is a thin adapter (~60 lines) — key normalization, then the four ops mapped onto the datastore, with blocking calls run in a thread so the async interface never blocks the event loop.

## Usage

```python
from strands.storage import Storage
from strands_postgres_storage import PostgresStorage   # or SQLStorage / MongoDBStorage / DynamoDBStorage

storage: Storage = PostgresStorage("postgresql://user:pass@localhost:5432/db")

await storage.write("sessions/abc/state.json", b"...bytes...")
data = await storage.read("sessions/abc/state.json")   # -> bytes | None
keys = await storage.list("sessions/")                 # sorted, prefix-matched
await storage.delete("sessions/abc/state.json")        # no-op if absent
```

Constructor cheatsheet:

=== "PostgreSQL / SQL"

    ```python
    from strands_postgres_storage import PostgresStorage
    PostgresStorage("postgresql://user:pass@host:5432/db")      # or engine=<Engine>
    # any SQLAlchemy DB:
    from strands_sql_storage import SQLStorage
    SQLStorage("sqlite:///state.db")
    ```

=== "MongoDB"

    ```python
    from strands_mongodb_storage import MongoDBStorage
    MongoDBStorage("mongodb://localhost:27017")
    ```

=== "DynamoDB"

    ```python
    from strands_dynamodb_storage import DynamoDBStorage
    DynamoDBStorage("strands_storage")   # table auto-created (PAY_PER_REQUEST)
    ```

## Data model

Each backend stores one record per key with a namespaced `prefix`; `list(prefix)` is a prefix scan returning full keys, sorted. An optional `prefix=` on the constructor namespaces all keys (multi-tenant). Tested against real PostgreSQL, MongoDB, and DynamoDB.

## License

MIT · part of the [strands-agents-session](https://github.com/skamalj/strands-agents-session) family.
