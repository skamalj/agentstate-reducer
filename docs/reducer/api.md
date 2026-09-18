# API Reference

## `MessageReducer`

```python
MessageReducer(min_messages=0, max_messages=None, *, config=None)
```

| Param | Default | Description |
|---|---|---|
| `min_messages` | `0` | Messages to retain after pruning (message-count mode) |
| `max_messages` | `None` | Threshold to trigger pruning (`None` = never prune in count mode) |
| `config` | `None` | A `ReducerConfig`. When provided, it overrides `min_messages`/`max_messages` |

If `config` is omitted, a `ReducerConfig` is built from `min_messages`/`max_messages`.

### Methods

#### `reduce(existing=None, new=None, namespace=None) -> ReducerResult`

Concatenates `existing + new`, then prunes if over threshold (count or token mode). `namespace` is an opaque value forwarded unchanged to every [`on_prune`](long-term-memory.md) hook; the reducer never inspects it.

```python
result = reducer.reduce(existing=history, new=[new_message])
result = reducer.reduce(existing=history, namespace=("memories", user_id))   # with on_prune hooks
```

#### `as_langgraph_reducer() -> Callable`

Returns a function with signature `(existing, new) -> list` for use with LangGraph's `Annotated[list, fn]` pattern. Returns only the surviving messages.

```python
class MyState(TypedDict):
    messages: Annotated[list, reducer.as_langgraph_reducer()]
```

---

## `ReducerConfig`

```python
ReducerConfig(
    min_messages=10,
    max_messages=20,
    max_tokens=None,
    target_tokens=None,
    token_counter=None,
    preserve_first=True,
    cascade_tool_messages=True,
    summarize_fn=None,
    inject_summary=False,
    summary_message_factory=None,
    on_prune=[],
    namespace_key="memory_namespace",
    dedupe_on_prune=True,
    dedupe_window=10_000,
)
```

| Field | Default | Description |
|---|---|---|
| `min_messages` | `10` | Messages to retain after pruning (message-count mode) |
| `max_messages` | `20` | Threshold to trigger pruning (message-count mode) |
| `max_tokens` | `None` | Token threshold to trigger pruning. When set, enables **token mode** (takes precedence over message-count mode) |
| `target_tokens` | `None` | Prune down to at or below this token count. Defaults to `max_tokens` |
| `token_counter` | `None` | `Callable[[message], int]`. When omitted: tiktoken if installed, else char heuristic |
| `preserve_first` | `True` | Never prune index 0 (system message) |
| `cascade_tool_messages` | `True` | Also prune ToolMessages linked to a pruned AIMessage |
| `summarize_fn` | `None` | `Callable[[list], str]` called with pruned messages |
| `inject_summary` | `False` | Insert the summary back into `surviving` in place of the pruned block (see [Summarization](summarization.md)) |
| `summary_message_factory` | `None` | `Callable[[str, int], list]` building the injected summary block |
| `on_prune` | `[]` | List of `RememberFn` — `(pruned, namespace) -> Any` — called after pruning (see [Long-Term Memory Hooks](long-term-memory.md)) |
| `namespace_key` | `"memory_namespace"` | Key that framework integrations read from per-call config to find the namespace to forward |
| `dedupe_on_prune` | `True` | Deliver each message id to hooks at most once per reducer instance |
| `dedupe_window` | `10000` | Bounded memory of delivered ids |

---

## `RememberFn`

```python
RememberFn = Callable[[List[Any], Any], Any]     # (pruned_messages, namespace) -> Any
```

The type of an `on_prune` hook. `namespace` is whatever the caller of `reduce()` forwarded, or `None`.

---

## `Background`

```python
Background(fn: RememberFn, *, workers: int = 2, max_pending: int = 1000)
```

Wraps a `RememberFn` so it runs on a bounded worker pool instead of inside the caller's `reduce()`. Copies the pruned list, drops (and counts in `.dropped`) when the backlog is full, swallows hook exceptions, drains at exit. `close(wait=True)` stops accepting work; usable as a context manager. See [Long-Term Memory Hooks](long-term-memory.md#running-hooks-off-the-request-path).

---

## `ReducerResult`

Returned by `reduce()`.

| Field | Type | Description |
|---|---|---|
| `surviving` | `list` | Messages that remain after pruning |
| `pruned` | `list` | Messages that were removed |
| `summary` | `str \| None` | Summary from `summarize_fn`, if configured and pruning occurred |

---

## `resolve_token_counter`

```python
resolve_token_counter(token_counter=None) -> Callable[[message], int]
```

Returns the effective per-message token counter using the three-layer resolution: user callable → tiktoken → character heuristic. Exposed for advanced use (e.g. pre-computing a budget). Most users never call this directly — `reduce()` uses it internally in token mode.

---

## Pruning rules (both modes)

- Only `ai`/`agent`/`assistant` and `human`/`user` messages are pruning candidates.
- `system`, `tool`, and `function` messages are never pruned directly.
- Index 0 is preserved when `preserve_first=True`.
- When an `ai` message is pruned, `tool` messages linked via `tool_call_id` are pruned too (`cascade_tool_messages=True`).
- Whole messages only — content is never truncated.
