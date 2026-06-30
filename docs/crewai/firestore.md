# CrewAI Persistence — Firestore

A CrewAI `FlowPersistence` backend for **Google Firestore** with **built-in message pruning**. It persists flow state between runs so your flows can resume from any prior step, and it can automatically cap your message history before each write — no changes to your flow code or state class required.

!!! note "Current version"
    `crewai-persistence-firestore` **0.1.0** · Requires **Python >=3.10,<3.14** and **crewai>=1.0.0**

## What it is

`FirestoreFlowPersistence` subclasses `crewai.flow.persistence.base.FlowPersistence` (a Pydantic `BaseModel` + ABC in CrewAI 1.x) and stores CrewAI flow state in Google Firestore. Unlike other Firestore backends, it accepts an optional [`MessageReducer`](../reducer/index.md) that prunes the message list at the persistence layer.

Persistence is keyed by the flow state's `id` field — the `flow_uuid`. `save_state` accepts either a Pydantic `BaseModel` or a plain dict; `load_state` returns a dict (or `None`).

## Installation

=== "Base"

    ```bash
    pip install crewai-persistence-firestore
    ```

=== "With pruning"

    ```bash
    pip install "crewai-persistence-firestore[reducer]"
    ```

The `[reducer]` extra pulls in `agentstate-reducer`, required only if you pass a `reducer`.

## Firestore setup

The backend uses Google Cloud Application Default Credentials (ADC).

=== "Local development"

    ```bash
    gcloud auth application-default login
    ```

=== "Service account (CI / prod)"

    ```bash
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
    ```

!!! warning "Native mode required"
    Your Firestore instance must be in **Native mode** (not Datastore mode). Collections are created automatically on first write — no manual schema setup required.

## Quick start

### Normal flow (dict or Pydantic state)

```python
from crewai.flow.flow import Flow, listen, start
from crewai.flow.persistence import persist
from crewai_persistence_firestore import FirestoreFlowPersistence

@persist(FirestoreFlowPersistence(project_id="my-gcp-project", collection="flow_states"))
class MyFlow(Flow):
    @start()
    def step_one(self):
        return {"status": "started", "counter": 1}

    @listen(step_one)
    def step_two(self, state):
        return {**state, "counter": state["counter"] + 1}

flow = MyFlow()
result = flow.kickoff()
```

### Conversational flow (with message history and pruning)

```python
from crewai.flow.flow import Flow, listen, start
from crewai.flow.persistence import persist
from agentstate_reducer import MessageReducer
from agentstate_reducer.models import ReducerConfig
from crewai_persistence_firestore import FirestoreFlowPersistence

reducer = MessageReducer(config=ReducerConfig(min_messages=10, max_messages=20))

persistence = FirestoreFlowPersistence(
    project_id="my-gcp-project",
    collection="flow_states",
    reducer=reducer,
    messages_key="messages",   # key in state that holds the message list
)

@persist(persistence)
class ChatFlow(Flow):
    @start()
    def chat(self):
        # messages accumulate here; pruning happens automatically at save time
        ...

flow = ChatFlow()
flow.kickoff()
```

!!! note "The `@persist` decorator"
    `@persist` is imported from `crewai.flow.persistence`. Applied to a `Flow` subclass with your persistence instance, it transparently calls `save_state` / `load_state` keyed by the flow state's `id` (the `flow_uuid`).

## API reference

### `FirestoreFlowPersistence(project_id, collection="flow_states", reducer=None, messages_key="messages")`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `project_id` | `str` | required | Google Cloud project ID |
| `collection` | `str` | `"flow_states"` | Firestore collection name |
| `reducer` | `MessageReducer` | `None` | Optional pruner — see [Built-in message pruning](#built-in-message-pruning) |
| `messages_key` | `str` | `"messages"` | Key in the state dict that holds the message list |

### Methods

| Method | Description |
|---|---|
| `init_db()` | No-op — Firestore needs no schema setup |
| `save_state(flow_uuid, method_name, state_data)` | Persist flow state; accepts a `BaseModel` or dict, applies the reducer if configured |
| `load_state(flow_uuid)` | Load state dict for the given flow UUID; returns `None` if not found |

## Built-in message pruning

Long-running conversational flows accumulate message history with every turn, inflating Firestore document size and eventually blowing past LLM context limits.

Pass a [`MessageReducer`](../reducer/index.md) and the backend prunes the message list inside `save_state()` before writing to Firestore. **Your flow code, state class, and node logic stay untouched.**

When `len(messages) > max_messages`, the oldest `human`/`ai` messages are removed until `min_messages` remain. System-prompt index 0, `system`/`function` messages, and `tool` messages (unless their parent `ai` message is pruned) are preserved.

!!! tip "Full reducer configuration"
    For `preserve_first`, `cascade_tool_messages`, `summarize_fn`, token budgeting, and role aliases, see the [reducer overview](../reducer/index.md) and [token budget](../reducer/token-budget.md) docs.

## Data model

Each flow run is stored as a single Firestore document at `{collection}/{flow_uuid}` — one document per flow run:

```
{collection}/
  {flow_uuid}          ← one document per flow run
```

The document contains all state fields plus persistence metadata:

| Field | Description |
|---|---|
| `_method_name` | Name of the flow method that triggered the save |
| `_saved_at` | ISO 8601 UTC timestamp of the last save |
| _user fields_ | All fields from the original state dict / Pydantic model |

!!! note "Metadata handling"
    Persistence metadata is stored under `_persistence_meta` and stripped on load, so `load_state` returns only your state fields.

Example stored document:

```json
{
  "user_id": "kamal",
  "messages": ["..."],
  "step_output": "some result",
  "_method_name": "process_input",
  "_saved_at": "2025-06-30T10:15:00.123456+00:00"
}
```
