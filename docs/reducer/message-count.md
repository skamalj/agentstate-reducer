# Message-Count Pruning

The default mode. Pruning triggers when the number of messages exceeds `max_messages`, and removes the oldest eligible messages until `min_messages` remain.

## Basic usage

```python
from agentstate_reducer import MessageReducer

reducer = MessageReducer(min_messages=10, max_messages=20)
result = reducer.reduce(existing=history, new=[new_message])
```

Or via `ReducerConfig` for the full set of options:

```python
from agentstate_reducer import MessageReducer, ReducerConfig

config = ReducerConfig(
    min_messages=10,
    max_messages=20,
    preserve_first=True,
    cascade_tool_messages=True,
)
reducer = MessageReducer(config=config)
```

## How the window works

When `len(existing + new) > max_messages`:

1. The pruning window is `[start, len - min_messages)`, where `start` is `1` if `preserve_first` else `0`.
2. Within that window, only `human`/`ai` messages (and their aliases) are removed.
3. `system`, `tool`, and `function` messages in the window are **kept**.
4. Tool-call cascade is applied (see below).

!!! note "preserve_first adds one"
    With `preserve_first=True`, index 0 is always retained **in addition to** `min_messages` of the recent tail. So the floor is effectively `min_messages + 1`.

## What is never pruned

- **Index 0** when `preserve_first=True` — typically the system prompt.
- **`system`, `tool`, `function`** messages — they're skipped as pruning candidates.

## Tool-call cascade

When `cascade_tool_messages=True` (default), pruning an `ai` message that issued tool calls also prunes the `tool` messages that answered those calls (matched by `tool_call_id`). This prevents orphaned tool results that would confuse the model.

```python
messages = [
    {"role": "system", "content": "sys"},
    {"role": "ai", "content": "", "tool_calls": [{"id": "tc1"}]},
    {"role": "tool", "content": "result", "tool_call_id": "tc1"},
    # ... many more messages ...
]
# If the ai message is pruned, the linked tool message goes with it.
```

## Role aliases

Role names are normalised before pruning rules apply:

| Input role | Treated as | Common source |
|---|---|---|
| `human` | `human` | LangChain canonical |
| `user` | `human` | OpenAI API format |
| `ai` | `ai` | LangChain canonical |
| `assistant` | `ai` | OpenAI API format |
| `agent` | `ai` | LangGraph task outputs, agent frameworks |
| `system` | `system` | preserved, never pruned |
| `tool` | `tool` | preserved unless cascade-pruned |

So OpenAI-format lists (`role: "user"` / `role: "assistant"`) work with no conversion.

## When to prefer this over token mode

- Message sizes are roughly uniform.
- You want simple, predictable limits (“keep the last 20 turns”).
- You don't want any token-counting dependency or overhead.

For context-window or cost control with variable message sizes, use [Token-Budget Pruning](token-budget.md).
