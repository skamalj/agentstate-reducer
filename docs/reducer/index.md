# agentstate-reducer

Framework-agnostic message pruning for AI agent state. Works with **LangGraph**, **CrewAI**, and **plain dicts** — zero required dependencies.

## Install

```bash
pip install agentstate-reducer
```

With token counting via tiktoken:

```bash
pip install "agentstate-reducer[tokens]"
```

**Requires Python 3.10+.**

## What it does

Given a list of messages, the reducer drops the oldest **whole** messages when the list grows too large, keeping the conversation manageable. It supports two pruning strategies:

- **[Message-count pruning](message-count.md)** — trigger at `max_messages`, keep `min_messages`.
- **[Token-budget pruning](token-budget.md)** — trigger at `max_tokens`, keep the most recent messages that fit `target_tokens`.

In both modes it:

- **never truncates** message content — only whole messages are removed,
- **preserves index 0** (the system prompt) by default,
- **cascades tool messages** — when an AI message with tool calls is pruned, its linked tool results are pruned too, so you never have orphaned tool messages,
- **normalises role aliases** — `user`→`human`, `assistant`/`agent`→`ai` — so OpenAI-format dicts and agent-framework outputs work without preprocessing,
- can optionally **[summarize](summarization.md)** what was pruned.

## Quick start

```python
from agentstate_reducer import MessageReducer

reducer = MessageReducer(min_messages=10, max_messages=20)

result = reducer.reduce(
    existing=[
        {"role": "system", "content": "You are helpful"},
        {"role": "human", "content": "Hello"},
        {"role": "ai", "content": "Hi there!"},
    ],
    new=[{"role": "human", "content": "New message"}],
)

result.surviving  # messages that remain
result.pruned     # messages that were removed
result.summary    # optional summary (if summarize_fn configured)
```

## Two ways to use it

=== "In a LangGraph state (Annotated)"

    Runs automatically on every state merge — you own the state:

    ```python
    from agentstate_reducer import MessageReducer
    from typing_extensions import Annotated, TypedDict

    reducer = MessageReducer(min_messages=10, max_messages=20)

    class MyState(TypedDict):
        messages: Annotated[list, reducer.as_langgraph_reducer()]
    ```

=== "At the persistence layer (reducer= param)"

    Runs inside the storage backend before each write — you don't need to own the state:

    ```python
    from agentstate_reducer import MessageReducer
    from langgraph_checkpoint_cosmosdb import CosmosDBSaver

    saver = CosmosDBSaver(
        database_name="mydb",
        container_name="checkpoints",
        reducer=MessageReducer(min_messages=10, max_messages=20),
    )
    ```

    The same `reducer=` parameter is available on all the [LangGraph](../langgraph/cosmosdb.md) and [CrewAI](../crewai/cosmosdb.md) integrations.

## Framework compatibility

The adapter layer uses duck typing and class-name inspection — no `langchain_core` import required.

| Message format | Supported |
|---|---|
| `{"role": "ai", "content": "..."}` | ✓ plain dict with `role` key |
| `{"role": "user", "content": "..."}` | ✓ OpenAI-format dict (normalised to `human`) |
| `{"role": "agent", "content": "..."}` | ✓ agent-framework dict (normalised to `ai`) |
| `{"type": "ai", "content": "..."}` | ✓ LangChain serialized dict |
| `AIMessage`, `HumanMessage`, … | ✓ LangChain `BaseMessage` subclasses |
| Any object with a `.type` attribute | ✓ duck-typing fallback |
