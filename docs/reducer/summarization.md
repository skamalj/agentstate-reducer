# Summarization

When messages are pruned, you can optionally generate a **summary** of what was removed — for example by calling an LLM — so the agent retains a compressed memory of earlier conversation instead of losing it entirely.

## Usage

Provide a `summarize_fn` on the config. It receives the list of pruned messages and returns a string:

```python
from agentstate_reducer import MessageReducer, ReducerConfig

def summarize(pruned_messages):
    # Call your LLM here, or build a summary however you like
    return f"Earlier, the user discussed {len(pruned_messages)} topics..."

config = ReducerConfig(
    min_messages=10,
    max_messages=20,
    summarize_fn=summarize,
)
reducer = MessageReducer(config=config)

result = reducer.reduce(existing=messages)
result.summary   # the string returned by summarize_fn (or None)
result.pruned    # the messages that were summarized
```

`summarize_fn` works in both message-count and token-budget modes — it's called whenever pruning actually removes messages.

## Behaviour

- Called **only when pruning occurs** and at least one message was removed.
- Receives `result.pruned` (the removed messages, in original order).
- Its return value is placed on `result.summary`.
- If it raises, the error is logged and pruning still succeeds — `result.summary` is left as `None`. Summarization never breaks the reduce.

## Persisting the summary

The reducer returns the summary; it does **not** decide where it goes. When using a persistence integration, you typically want to fold the summary back into your state (e.g. a `conversation_summary` field or a synthetic system message) so the model sees it on the next turn.

!!! note "Integration support"
    The persistence integrations currently store `result.surviving`. If you need the summary persisted automatically, fold it into state in your own node/step logic, or open an issue — first-class summary persistence is on the roadmap.

## Example: LLM-backed summary

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini")

def summarize(pruned):
    text = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in pruned)
    resp = llm.invoke(f"Summarize this conversation excerpt concisely:\n\n{text}")
    return resp.content

config = ReducerConfig(max_tokens=4000, target_tokens=2000, summarize_fn=summarize)
```
