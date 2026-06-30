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

#### `reduce(existing=None, new=None) -> ReducerResult`

Concatenates `existing + new`, then prunes if over threshold (count or token mode).

```python
result = reducer.reduce(existing=history, new=[new_message])
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
