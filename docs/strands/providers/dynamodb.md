# DynamoDB Provider

`strands-session-dynamodb` is an Amazon DynamoDB storage backend for [Strands Agents](https://strandsagents.com). It implements the core [`SessionStorage`](../core/index.md) interface, so all of the session lifecycle logic — message indexing, restore, `removed_message_count` offsetting, tool-use repair, and change detection — is reused unchanged from the core. This package supplies only the DynamoDB storage.

!!! info "Storage only, by design"
    Message *pruning* in Strands is the job of a `ConversationManager` (`SlidingWindow`, `Summarizing`), deliberately decoupled from storage. This package does **not** prune — pruning at the storage layer would corrupt Strands' message-index/offset restore logic. Use a `conversation_manager` for that.

## Installation

Requires **Python 3.10+**.

=== "Standalone"

    ```bash
    pip install strands-session-dynamodb
    ```

=== "Family extra"

    ```bash
    pip install "strands-agents-session[dynamodb]"
    ```

## Why DynamoDB instead of S3

Strands ships an `S3SessionManager` out of the box, so why DynamoDB? Because agent sessions are a **request-bound, small-item** workload — the exact shape where DynamoDB wins on both cost and latency.

Strands writes **one item per message** plus an agent record re-synced each turn — lots of tiny (sub-KB) reads and writes. The bill is dominated by *request count*, not bytes stored, and that is where the two services price very differently:

| | S3 Standard | DynamoDB on-demand |
|---|---|---|
| Write | ~$5.00 / million PUT (any size) | ~$1.25 / million WRU (per 1 KB) |
| Read | ~$0.40 / million GET (per object) | ~$0.25 / million RRU (per 4 KB) |
| Free tier | none | 25 WCU + 25 RCU + 25 GB, perpetual |
| Latency | tens of ms | single-digit ms |

Two structural advantages for small items:

- **Writes:** S3 charges per request regardless of size — a 200-byte message costs the same PUT as a 4 MB one. DynamoDB bills per KB, so tiny messages hit the cheapest unit *and* the per-unit price is ~4x lower.
- **Reads:** `list_messages` is **one Query** in DynamoDB, and one RRU covers 4 KB — so several small messages per RRU. In S3 it is **one GET per message object**. Batching crushes the per-item read cost.

For a workload of ~1M small message-writes/month with periodic restores, this is roughly a **3–4x lower bill** on DynamoDB — and often **free** under DynamoDB's perpetual free tier, which S3 has no equivalent of. Add native **TTL** for automatic session expiry and single-digit-ms access, and DynamoDB is the better default for hot session/agent-state storage.

!!! note "When S3 still wins"
    Very large message payloads (big tool results, images) that approach or exceed DynamoDB's 400 KB item limit, or cold/archival sessions rarely read (S3 storage is ~10x cheaper per GB). A robust production setup is DynamoDB for the session/message records + S3 overflow only for oversized blobs.

## Quick start

```python
from strands import Agent
from strands_session_dynamodb import DynamoDBSessionManager

session_manager = DynamoDBSessionManager(
    session_id="user-123",
    table_name="strands-sessions",
    region_name="us-east-1",
)

agent = Agent(session_manager=session_manager)

agent("Hi, I'm Kamal")
agent("What's my name?")   # remembers within the session
```

Next run, same `session_id` → the agent restores its full history and state from DynamoDB. The table is created automatically (on-demand billing) if it does not exist.

## Constructor parameters

`DynamoDBSessionManager(session_id, table_name, *, region_name=None, boto_session=None, boto_client_config=None, endpoint_url=None, ttl_seconds=None)`

| Parameter | Description |
|---|---|
| `session_id` | Session identifier |
| `table_name` | DynamoDB table (auto-created if absent) |
| `region_name` | AWS region |
| `boto_session` | Optional pre-built `boto3.Session` |
| `boto_client_config` | Optional `botocore` client config |
| `endpoint_url` | Custom endpoint (e.g. DynamoDB Local / LocalStack) |
| `ttl_seconds` | If set, writes a `ttl` epoch attribute and enables table TTL for automatic session expiry |

The table is **auto-created** with on-demand billing on first use if it does not already exist. For credential resolution and the full auth surface, see [Authentication](../concepts/auth.md).

## Data model

Single table, both keys strings:

| Item | PK | SK |
|---|---|---|
| Session | `SESSION#<session_id>` | `META` |
| Agent | `SESSION#<session_id>` | `AGENT#<agent_id>` |
| Message | `SESSION#<session_id>#AGENT#<agent_id>` | `MSG#<zero-padded id>` |

Messages live in a per-agent partition with a zero-padded, lexically ordered sort key, so `list_messages(offset, limit)` is a native range Query — matching the `removed_message_count` offset semantics Strands relies on. Payloads are stored as a JSON string.

!!! warning "Item-size cap: 400 KB"
    DynamoDB items are capped at 400 KB. A single message with a very large payload (big tool results / images) could exceed that; S3 has no such limit. For those workloads, keep large blobs in S3 and reference them.

## See also

- [What You Get](../core/index.md) — the shared `SessionStorage` contract this provider implements.
- [Build Your Own Backend](../core/building-a-backend.md) — write a storage backend of your own.
- [Authentication](../concepts/auth.md) — the full boto3 credential surface.

---

*Version 0.1.0 · MIT License*
