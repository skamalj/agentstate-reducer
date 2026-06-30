# Token-Budget Pruning

Instead of counting messages, prune to a **token budget** — ideal for staying within a model's context window or controlling cost. Set `max_tokens` and the reducer switches from message-count mode to token mode.

## Basic usage

```python
from agentstate_reducer import MessageReducer, ReducerConfig

# Prune when the conversation exceeds 4000 tokens, down to ~2000
config = ReducerConfig(max_tokens=4000, target_tokens=2000)
reducer = MessageReducer(config=config)

result = reducer.reduce(existing=messages, new=new_messages)
# result.surviving stays within ~2000 tokens
```

## Whole messages only — never truncated

The reducer never cuts message content. It drops **whole messages**, keeping:

- the preserved first message (system prompt), and
- the most recent messages that fit within `target_tokens`.

This guarantees you never hand a model a half-cut message. The "stay within 2000–4000 tokens" behaviour is achieved purely by dropping older whole messages.

## `max_tokens` vs `target_tokens`

| Field | Role |
|---|---|
| `max_tokens` | Pruning **triggers** when the total exceeds this |
| `target_tokens` | Pruning reduces **down to** at or below this (defaults to `max_tokens`) |

Setting `target_tokens` below `max_tokens` creates **hysteresis**: prune at 4000, down to 2000, so pruning runs less often instead of firing on every single message once you're near the ceiling.

```python
# Fires at 4000, trims to 2000 — fewer, larger prunes
ReducerConfig(max_tokens=4000, target_tokens=2000)

# Fires and trims at the same 3000 — prunes more frequently, smaller trims
ReducerConfig(max_tokens=3000)
```

## How tokens are counted

The counter is resolved in **three layers**, highest priority first:

### 1. User-supplied `token_counter`

A `Callable[[message], int]` you pass on the config. Use this for exact, model-specific counting:

```python
import tiktoken
enc = tiktoken.encoding_for_model("gpt-4o")

config = ReducerConfig(
    max_tokens=4000,
    token_counter=lambda m: len(enc.encode(m.get("content", ""))),
)
```

### 2. tiktoken (automatic)

If `tiktoken` is installed, the `cl100k_base` encoding is used automatically — accurate for OpenAI-family models. No counter to write:

```bash
pip install "agentstate-reducer[tokens]"
```

```python
config = ReducerConfig(max_tokens=4000)  # uses tiktoken under the hood
```

### 3. Character heuristic (fallback)

If no counter is given and tiktoken isn't installed, the reducer estimates `len(content) / 4` plus a small per-message overhead. Dependency-free and fine for approximate budgeting.

!!! tip "Resolution is automatic"
    You don't choose a layer explicitly — `resolve_token_counter()` picks the best available. Pass a `token_counter` only when you need exact, model-specific counts.

## Interaction with other options

- **Token mode takes precedence**: if `max_tokens` is set, `max_messages`/`min_messages` are ignored.
- **`preserve_first`** still applies — index 0 is always retained and its tokens are reserved off the top of the budget.
- **`cascade_tool_messages`** still applies — orphaned tool results are removed with their parent AI message.

## When to prefer this over message-count mode

- You care about the model's context window or per-call cost.
- Message sizes vary a lot (a 5-token "yes" vs a 2000-token document dump).
- You want a budget expressed in the same unit the model bills in.

For simple, uniform limits, [Message-Count Pruning](message-count.md) is lighter.
