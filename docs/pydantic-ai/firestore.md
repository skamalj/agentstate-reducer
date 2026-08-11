# PydanticAI Persistence — Firestore

A PydanticAI **`StepStore`** and **message-history** store backed by **Google Firestore**. Both stores share one Firestore root collection and one `AsyncKV` implementation — see [StepStore & History](concepts.md) for the layers.

!!! note "Current version"
    `pydantic-ai-firestore-persistence` **0.1.0** · Requires **Python >=3.10**, **pydantic-ai>=1.0**, and **google-cloud-firestore**

## What it is

`FirestoreAsyncKV` implements the core [`AsyncKV`](concepts.md#the-asynckv-interface) over Firestore (sync SDK offloaded to a thread executor). On top of it:

- `FirestoreStepStore` — PydanticAI's async `StepStore` (events, snapshots, tool-effect ledger).
- `FirestoreHistoryStore` — `save`/`load` chat history by conversation id.

Layout: each partition key maps to a document `<root>/<enc(PK)>` whose `items` subcollection holds one doc per sort key, `<enc(SK)>` → `{SK, data}`. Doc ids are URL-encoded (Firestore ids can't contain `/`); the raw `SK` is a field so prefix/range queries work within a subcollection without extra indexes.

## Installation

=== "Via extra"

    ```bash
    pip install "pydantic-ai-persistence[firestore]"
    ```

=== "Direct"

    ```bash
    pip install pydantic-ai-firestore-persistence
    ```

## Authentication

Firestore uses **Application Default Credentials**:

=== "Local (gcloud)"

    ```bash
    gcloud auth application-default login
    ```

=== "Service account"

    ```bash
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
    ```

=== "GCP runtime"

    On Cloud Run / GKE / GCE the attached service account is used automatically — pass nothing extra.

```python
store = FirestoreStepStore(project_id="my-gcp-project")
```

## Quick start

### History

```python
from pydantic_ai import Agent
from pydantic_ai_firestore_persistence import FirestoreHistoryStore

agent = Agent("openai:gpt-4o")
store = FirestoreHistoryStore(project_id="my-gcp-project")

result = agent.run_sync("Hi, I'm Kamal")
await store.save("conv-1", result.all_messages())

prior = await store.load("conv-1")
result = agent.run_sync("What's my name?", message_history=prior)
```

### Step persistence

```python
from pydantic_ai import Agent
from pydantic_ai_harness.step_persistence import StepPersistence
from pydantic_ai_firestore_persistence import FirestoreStepStore

step_store = FirestoreStepStore(
    project_id="my-gcp-project",
    root_collection="pai_persistence",
    max_snapshots_per_run=10,
)
agent = Agent("openai:gpt-4o", capabilities=[StepPersistence(store=step_store)])
```

## API reference

### `FirestoreStepStore(*, project_id, root_collection="pai_persistence", client=None, max_snapshots_per_run=None)`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_id` | `str` | required | GCP project id |
| `root_collection` | `str` | `"pai_persistence"` | Top-level collection under which per-partition docs live |
| `client` | `firestore.Client \| None` | `None` | Pre-built client (else one is created from `project_id`) |
| `max_snapshots_per_run` | `int \| None` | `None` | Retain only the newest N snapshots per run; unbounded if `None` |

### `FirestoreHistoryStore(*, project_id, root_collection="pai_persistence", client=None)`

Same connection parameters (no snapshot pruning — history is a single record per conversation).

### `FirestoreAsyncKV(*, project_id, root_collection="pai_persistence", client=None)`

The raw KV layer if you want to build your own store on the same collection.

## Data model

`<root>/<enc(PK)>/items/<enc(SK)>` → `{SK, data}`. Prefix scans use a `SK >= prefix` / `SK < prefix + ` range with `order_by("SK")`, so no composite indexes are needed. `KVStepStore` maps runs, events, snapshots, and the tool ledger onto these keys — see the [key layout](concepts.md#key-layout).

!!! warning "Beta harness feature"
    `StepStore` is a **beta/experimental** PydanticAI harness feature; its API may still change. `FirestoreHistoryStore` does not depend on it.
