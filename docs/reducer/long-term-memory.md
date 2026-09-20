# Long-Term Memory Hooks (`on_prune`)

!!! success "New in agentstate-reducer 0.4.0"
    Messages leaving the context window are handed to any callable you supply — the exact moment they stop being visible to the model. Wire that callable to a LangGraph `BaseStore`, LangMem, a Strands `MemoryStore`, or any memory engine. **The reducer stays zero-dependency**: it never imports a store, a framework, or an LLM.

## Why prune-time is the right moment

Short-term memory (the checkpoint / session) and long-term memory (the store) are two separate pipes in every framework. Nothing built-in moves conversation history from one to the other; you normally add a node, a callback, or a scheduler and then track what you have already extracted.

The reducer already sits inside the persistence path and already computes the boundary: **`pruned` is precisely the slice about to be forgotten.** Hooking there gives you:

- a semantically meaningful trigger — *this is leaving the model's view, decide now*,
- exactly the new slice, no cursor bookkeeping,
- one hook body that works across every framework that runs the reducer.

```
persistence.put(...)
   └─ reducer.reduce(existing=messages, namespace=...)
        ├─ surviving ──► persisted   (short-term: thread / session)
        └─ pruned ─────► on_prune hooks ──► store.put(namespace, ...)   (long-term: user)
```

## Usage

```python
from uuid import uuid4
from agentstate_reducer import MessageReducer, ReducerConfig, Background

def remember(pruned, namespace):
    for m in pruned:
        store.put(namespace, key=str(uuid4()), value={"role": m.type, "content": m.content})

reducer = MessageReducer(config=ReducerConfig(
    max_messages=20,
    on_prune=[remember],               # cheap hook: runs inline
    # on_prune=[Background(remember)]   # slow hook (LLM extraction): off the request path
))
```

A hook is any `RememberFn = Callable[[list, Any], Any]`, called as `hook(pruned_messages, namespace)`. Hooks run in order; one that raises is logged and skipped, and never breaks the reduce.

## Where the namespace comes from

The store needs a **namespace** (the user, tenant, or account the memory belongs to). Pruned messages do not carry one, and the reducer is constructed once for every request, so it cannot be a static config value. Instead:

1. `reduce(..., namespace=X)` forwards `X` **untouched** to every hook. The reducer never inspects it.
2. Framework integrations look up `ReducerConfig.namespace_key` (default `"memory_namespace"`) in their per-call config or state, and pass what they find.
3. The **app** decides the value, in the one place that knows the user.

=== "LangGraph"

    ```python
    graph.invoke(input, config={"configurable": {
        "thread_id": uuid4().hex,                     # short-term scope (checkpoint)
        "memory_namespace": ("memories", user.id),    # long-term scope (store)
    }})
    ```

    All three checkpointers ([DynamoDB](../langgraph/dynamodb.md), [CosmosDB](../langgraph/cosmosdb.md), [Firestore](../langgraph/firestore.md)) read it from `config["configurable"]` on every `put()`.

=== "CrewAI"

    Put `memory_namespace` in your flow state model; every `crewai-persistence-*` package (0.2.0+) reads it from the state on `save_state` and falls back to `"/flow/<flow_uuid>"`. In CrewAI the namespace is a `Memory` **scope path string**, so the hook can pass it straight to `memory.remember(..., scope=namespace)`. See [CrewAI Memory Backends](../crewai/memory.md).

If the app never sets it, integrations fall back to a per-thread namespace such as `("memories", thread_id)`. Callers that pass no `namespace` at all get `None` — old code keeps working unchanged.

!!! tip "Different key name?"
    If your app already carries the scope under another key, point the reducer at it: `ReducerConfig(namespace_key="tenant")`.

## Exactly-once delivery

Persistence layers often call `reduce()` several times per turn on overlapping lists — LangGraph writes a checkpoint per super-step, and the in-memory graph state is never the reduced copy, so consecutive saves would prune the same leading messages again. The reducer therefore remembers which message ids it has already handed to hooks:

| Field | Default | Meaning |
|---|---|---|
| `dedupe_on_prune` | `True` | Deliver each message id to hooks at most once per reducer instance |
| `dedupe_window` | `10000` | Bounded memory of delivered ids (oldest evicted) |

Messages without an id are always delivered. `ReducerResult.pruned` is **never** filtered — only what the hooks see.

## Running hooks off the request path

`on_prune` fires inside the persistence layer's save, which is on the request path. A plain `store.put` is fine inline; an LLM extraction call is not. Wrap it:

```python
on_prune=[Background(remember)]
```

`Background(fn, workers=2, max_pending=1000)`:

- copies the pruned list before handing it to a worker,
- bounds the backlog and **drops** (with a warning, counted in `.dropped`) when the pool falls too far behind — losing one batch is recoverable, blocking the request is not,
- swallows and logs hook exceptions,
- drains queued work at interpreter exit.

!!! warning "Serverless"
    Runtimes that freeze the process after the response (AWS Lambda, Cloud Run with CPU throttling) can strand queued work. Call `bg.close()` at the end of the handler, or use the inline form.

## Pairing with LangMem or an extraction engine

`on_prune` only decides *when*. What to store is the hook's business, so the natural pairing is an extractor inside the hook:

```python
manager = create_memory_store_manager("anthropic:claude-sonnet-5", namespace=("memories", "{user_id}"))

def remember(pruned, namespace):
    manager.invoke({"messages": pruned}, config={"configurable": {"user_id": namespace[-1]}})

on_prune=[Background(remember)]
```

LangMem still does extraction and consolidation into the store; the reducer just replaced its clock with a better one. Swap the body for any other engine and nothing else moves.

## Worked example (LangGraph + DynamoDB)

```python
from uuid import uuid4
from langgraph.graph import StateGraph, START, END
from langgraph.store.memory import InMemoryStore          # any BaseStore
from agentstate_reducer import MessageReducer, ReducerConfig
from langgraph_dynamodb_checkpoint import DynamoDBSaver

store = InMemoryStore()

def remember(pruned, namespace):
    for m in pruned:
        store.put(tuple(namespace), key=str(uuid4()), value={"role": m.type, "content": m.content})

reducer = MessageReducer(config=ReducerConfig(min_messages=4, max_messages=6, on_prune=[remember]))
saver = DynamoDBSaver("checkpoints", reducer=reducer)
graph = builder.compile(checkpointer=saver, store=store)

cfg = {"configurable": {"thread_id": uuid4().hex, "memory_namespace": ("memories", "kamal")}}
for i in range(5):
    graph.invoke({"messages": [("user", f"turn {i}")]}, config=cfg)

store.search(("memories", "kamal"))   # the turns that left the window, once each
```

This is the shape of the e2e test that ships with each checkpointer.
