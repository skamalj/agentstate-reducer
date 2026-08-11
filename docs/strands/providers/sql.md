# SQL Provider (SQLAlchemy)

`strands-session-sql` is a single provider that works with **any SQL database SQLAlchemy supports** — SQLite, PostgreSQL, MySQL, and more — selected purely by connection URL. It's the Python equivalent of "JDBC backends": one API, many databases.

## Installation

```bash
pip install strands-session-sql                       # SQLite works out of the box (built-in)
pip install "strands-session-sql[postgres]"           # + psycopg (PostgreSQL)
pip install "strands-session-sql[mysql]"              # + pymysql (MySQL)
# or via the family extra:
pip install "strands-agents-session[sql]"
```

**Requires Python 3.10+.** SQLite needs no driver (Python's built-in `sqlite3`); other databases need their SQLAlchemy driver (installed via the extras above).

## Quick start

=== "SQLite (file)"

    ```python
    from strands import Agent
    from strands_session_sql import SQLSessionManager

    agent = Agent(session_manager=SQLSessionManager(
        session_id="user-123",
        url="sqlite:///sessions.db",
    ))
    ```

=== "PostgreSQL"

    ```python
    from strands_session_sql import SQLSessionManager

    session_manager = SQLSessionManager(
        session_id="user-123",
        url="postgresql+psycopg://user:pass@localhost:5432/mydb",
    )
    ```

=== "MySQL"

    ```python
    from strands_session_sql import SQLSessionManager

    session_manager = SQLSessionManager(
        session_id="user-123",
        url="mysql+pymysql://user:pass@localhost:3306/mydb",
    )
    ```

The table is created automatically if it does not exist.

## API

### `SQLSessionManager(session_id, *, url=None, table_name="strands_sessions", engine=None)`

| Parameter | Description |
|---|---|
| `session_id` | Session identifier |
| `url` | SQLAlchemy connection URL (e.g. `sqlite:///sessions.db`, `postgresql+psycopg://…`) |
| `table_name` | Table name (default `strands_sessions`; created if absent) |
| `engine` | Optional pre-built SQLAlchemy `Engine` to reuse (for pooling / custom config) — supply this **or** `url` |

## Authentication

SQL auth is carried in the **connection URL** (username/password, host, TLS query args), or via a pre-built SQLAlchemy `Engine` for advanced setups (custom pools, SSL certs, IAM auth plugins). Examples:

```text
postgresql+psycopg://user:pass@host:5432/db?sslmode=require
mysql+pymysql://user:pass@host/db?ssl_ca=/path/ca.pem
sqlite:///relative/path.db      sqlite:////absolute/path.db      sqlite:///:memory:
```

For anything the URL can't express, build an `Engine` yourself and pass `engine=`.

## Data model

A single table, composite primary key `(pk, sk)`, with a `data` column holding the serialized payload:

```sql
CREATE TABLE strands_sessions (
    pk   VARCHAR NOT NULL,
    sk   VARCHAR NOT NULL,
    data TEXT    NOT NULL,
    PRIMARY KEY (pk, sk)
);
```

`list_messages(offset, limit)` maps to `WHERE pk = ? AND sk >= ? ORDER BY sk LIMIT ?`. Message sort keys are zero-padded so lexical ordering matches numeric ordering, matching Strands' `removed_message_count` offset semantics.

## When to use SQL

- You already run Postgres/MySQL and want sessions in the same database as the rest of your app (transactions, backups, ops tooling in one place).
- You want a **zero-infrastructure** file-based option for local/dev — `sqlite:///sessions.db`.
- You want portability across SQL engines without changing code — just the URL.

See [Build Your Own Backend](../core/building-a-backend.md) for the plain-`sqlite3` version this generalizes.
