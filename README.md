# agentstate-reducer

Framework-agnostic message reducer for AI agent state management. Works with **LangGraph**, **CrewAI**, and **plain dicts**.

## What It Does

Automatically prunes message history when it exceeds a threshold, keeping conversations manageable:

- **Windowed pruning**: Trigger at `max_messages`, retain `min_messages`
- **Token-budget pruning**: Trigger at `max_tokens`, prune down to `target_tokens` — whole messages only, never truncated
- **System message preservation**: Index 0 (system prompt) is never pruned (configurable)
- **ToolMessage cascade**: When an AI message is pruned, linked ToolMessages are pruned too
- **Optional summarization**: Callback with pruned messages to generate an LLM summary
- **Role alias normalisation**: Understands `user`/`assistant`/`agent` in addition to `human`/`ai` — works with OpenAI-format dicts and agent framework outputs out of the box
- **Framework-agnostic**: Works with plain dicts, LangChain `BaseMessage` subclasses, or any duck-typed message object — zero dependencies

## Install

```bash
pip install agentstate-reducer
```

**Zero dependencies.** Works with Python 3.10+.

## Quick Start

```python
from agentstate_reducer import MessageReducer

reducer = MessageReducer(min_messages=10, max_messages=20)

# Works with plain dicts
result = reducer.reduce(
    existing=[
        {"role": "system", "content": "You are helpful"},
        {"role": "human", "content": "Hello"},
        {"role": "ai", "content": "Hi there!"},
    ],
    new=[{"role": "human", "content": "New message"}],
)
print(result.surviving)  # Messages that remain
print(result.pruned)     # Messages that were removed

# Works with LangChain BaseMessage objects too
from langchain_core.messages import HumanMessage, AIMessage
result = reducer.reduce(
    existing=[HumanMessage(content="Hello")],
    new=[AIMessage(content="Hi!")],
)
```

## LangGraph Integration

Use directly as a state annotation — the reducer runs automatically on every state update:

```python
from agentstate_reducer import MessageReducer
from typing_extensions import Annotated, TypedDict

reducer = MessageReducer(min_messages=10, max_messages=20)

class MyState(TypedDict):
    messages: Annotated[list, reducer.as_langgraph_reducer()]
```

`as_langgraph_reducer()` returns a `(existing, new) -> list` function that LangGraph calls on every state merge.

## CosmosDB Checkpoint Integration

When using `langgraph-checkpoint-cosmosdb`, pass a `MessageReducer` to reduce messages at the persistence layer — useful when you don't control the state definition:

```python
from agentstate_reducer import MessageReducer
from langgraph_checkpoint_cosmosdb import CosmosDBSaver

reducer = MessageReducer(min_messages=10, max_messages=20)
saver = CosmosDBSaver(
    database_name="mydb",
    container_name="checkpoints",
    reducer=reducer,           # applied before each checkpoint is stored
    messages_key="messages",   # which channel holds the message list (default)
)
```

## Summarization

Provide a `summarize_fn` to generate a summary of pruned messages (e.g. via an LLM):

```python
from agentstate_reducer import MessageReducer, ReducerConfig

def summarize(pruned_messages):
    # Call your LLM here
    return f"Summary of {len(pruned_messages)} pruned messages"

config = ReducerConfig(
    min_messages=10,
    max_messages=20,
    summarize_fn=summarize,
)
reducer = MessageReducer(config=config)
result = reducer.reduce(existing=messages)
print(result.summary)  # "Summary of 5 pruned messages"
```

`result.summary` is **always returned** when a `summarize_fn` is set — you can store or display it however you like.

### Injecting the summary back into the conversation

By default the summary is only *returned*, not added to the surviving messages. Set `inject_summary=True` to also insert it in place of the pruned block, so the model sees it on the next turn:

```python
config = ReducerConfig(
    min_messages=10,
    max_messages=20,
    summarize_fn=summarize,
    inject_summary=True,
)
```

The default injection is a **`human` + `ai` pair** — a human message carrying the summary followed by a short `ai` acknowledgement (`"OK"`):

```
[system] → [human: "Here is the summary of previous N messages: ..."] → [ai: "OK"] → [recent tail]
```

Why a pair? It keeps the conversation well-formed for providers that require strict role alternation (`system → human → ai → …`). Because both messages are ordinary `human`/`ai` messages at the **front** of the window, the *next* prune sweeps them into the new summary automatically — so there is always **exactly one** summary block, with no accumulation and no bookkeeping.

**Custom shape.** Override `summary_message_factory` — a `Callable[[summary_text, pruned_count], list[message]]` — to inject a single message or a provider-specific shape:

```python
config = ReducerConfig(
    summarize_fn=summarize,
    inject_summary=True,
    # inject just one system message instead of the human/ai pair
    summary_message_factory=lambda text, n: [{"role": "system", "content": f"Summary ({n} msgs): {text}"}],
)
```

> The summary is placed **where the pruned messages were** — after `preserve_first`, before the retained recent tail — never at index 0 (the system prompt is preserved). When used with a checkpoint/persistence saver that stores `result.surviving`, the injected summary is persisted automatically with no saver changes.

## Token-Budget Pruning

Instead of counting messages, you can prune to a **token budget** — useful when you want to stay within a model's context window or control cost. Set `max_tokens` and pruning switches from message-count mode to token mode.

```python
from agentstate_reducer import MessageReducer, ReducerConfig

# Prune when the conversation exceeds 4000 tokens, down to ~2000
config = ReducerConfig(max_tokens=4000, target_tokens=2000)
reducer = MessageReducer(config=config)

result = reducer.reduce(existing=messages, new=new_messages)
# result.surviving stays within ~2000 tokens; whole messages only — never truncated
```

**Whole messages only.** The reducer never truncates message content — it drops whole messages, keeping the most recent ones that fit the budget, plus the preserved first message. This guarantees you never send a model a half-cut message.

**`max_tokens` vs `target_tokens`.** Pruning *triggers* when the total exceeds `max_tokens`, and reduces down to `target_tokens` (defaults to `max_tokens` if not set). Setting `target_tokens` lower than `max_tokens` creates hysteresis — prune at 4000, down to 2000 — so pruning runs less often.

### How tokens are counted

The counter is resolved in three layers (highest priority first):

1. **User-supplied `token_counter`** — a `Callable[[message], int]` you pass on the config. Use this for exact, model-specific counting:
   ```python
   import tiktoken
   enc = tiktoken.encoding_for_model("gpt-4o")
   config = ReducerConfig(
       max_tokens=4000,
       token_counter=lambda m: len(enc.encode(m.get("content", ""))),
   )
   ```
2. **tiktoken** — if installed (`pip install "agentstate-reducer[tokens]"`), the `cl100k_base` encoding is used automatically. Accurate for OpenAI-family models.
3. **Character heuristic** — `len(content) / 4` plus a small per-message overhead. Dependency-free fallback, fine for approximate budgeting.

Install with tiktoken support:

```bash
pip install "agentstate-reducer[tokens]"
```

> Token mode takes precedence over message-count mode: if `max_tokens` is set, `max_messages`/`min_messages` are ignored. `preserve_first` and `cascade_tool_messages` apply in both modes.

## Pruning Behaviour

- Only `ai`/`agent`/`assistant` and `human`/`user` messages are candidates for pruning.
- `system`, `tool`, and `function` messages are never pruned directly.
- Index 0 is preserved by default (`preserve_first=True`) — typically the system prompt.
- When an `ai` message is pruned, all `tool` messages linked to it via `tool_call_id` are also pruned (`cascade_tool_messages=True`).
- Pruning is windowed: once `len(existing + new) > max_messages`, oldest eligible messages are removed until `min_messages` remain.

## Role Aliases

The reducer normalises common role name variants before applying pruning rules, so you don't need to convert message formats:

| Input role | Treated as | Common source |
|---|---|---|
| `human` | `human` | LangChain canonical |
| `user` | `human` | OpenAI API format |
| `ai` | `ai` | LangChain canonical |
| `assistant` | `ai` | OpenAI API format |
| `agent` | `ai` | LangGraph task outputs, agent frameworks |
| `system` | `system` | preserved, never pruned |
| `tool` | `tool` | preserved unless cascade-pruned |

This means OpenAI-format message lists (`role: "user"` / `role: "assistant"`) work without any preprocessing.

## Framework Compatibility

The adapter layer uses duck typing and class-name inspection — no `langchain_core` import required:

| Message format | Supported |
|---|---|
| `{"role": "ai", "content": "..."}` | ✓ plain dict with `role` key |
| `{"role": "user", "content": "..."}` | ✓ OpenAI-format dict (normalised to `human`) |
| `{"role": "agent", "content": "..."}` | ✓ agent framework dict (normalised to `ai`) |
| `{"type": "ai", "content": "..."}` | ✓ plain dict with `type` key (LangChain serialized) |
| `AIMessage`, `HumanMessage`, etc. | ✓ LangChain `BaseMessage` subclasses |
| Any object with `.type` attribute | ✓ duck typing fallback |

## API Reference

### `MessageReducer(min_messages, max_messages, *, config)`

| Param | Default | Description |
|---|---|---|
| `min_messages` | `0` | Messages to retain after pruning |
| `max_messages` | `None` | Threshold to trigger pruning (`None` = never prune) |
| `config` | `None` | `ReducerConfig` object (overrides `min_messages`/`max_messages`) |

### `ReducerConfig`

| Field | Default | Description |
|---|---|---|
| `min_messages` | `10` | Messages to retain after pruning (message-count mode) |
| `max_messages` | `20` | Threshold to trigger pruning (message-count mode) |
| `max_tokens` | `None` | Token threshold to trigger pruning. When set, enables token mode (takes precedence over message-count mode) |
| `target_tokens` | `None` | Prune down to at or below this token count. Defaults to `max_tokens` |
| `token_counter` | `None` | `Callable[[message], int]`. When omitted: tiktoken if installed, else char heuristic |
| `preserve_first` | `True` | Never prune index 0 (system message) |
| `cascade_tool_messages` | `True` | Also prune ToolMessages linked to a pruned AIMessage |
| `summarize_fn` | `None` | `Callable[[list], str]` called with pruned messages |

### `reducer.reduce(existing, new) -> ReducerResult`

| Field | Type | Description |
|---|---|---|
| `surviving` | `list` | Messages that remain |
| `pruned` | `list` | Messages that were removed |
| `summary` | `str \| None` | Summary from `summarize_fn` if configured |

### `reducer.as_langgraph_reducer() -> Callable`

Returns a function with signature `(existing, new) -> list` for use with LangGraph's `Annotated[list, fn]` pattern.
