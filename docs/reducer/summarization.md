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

### Folding the summary into state

The pattern is the same everywhere: run the reducer **yourself**, then write both `result.surviving` (the capped messages) and `result.summary` (the compressed memory of what was dropped) into your state before it's persisted. Keep a rolling `conversation_summary` so successive prunes accumulate rather than overwrite.

=== "LangGraph (in a node)"

    ```python
    from typing import Annotated, TypedDict
    from agentstate_reducer import MessageReducer, ReducerConfig

    reducer = MessageReducer(config=ReducerConfig(
        min_messages=10, max_messages=20, summarize_fn=summarize,
    ))

    class State(TypedDict):
        messages: list
        conversation_summary: str        # persisted alongside messages

    def prune_node(state: State) -> State:
        result = reducer.reduce(existing=state["messages"])

        summary = state.get("conversation_summary", "")
        if result.summary:               # only set when pruning actually dropped messages
            summary = f"{summary}\n{result.summary}".strip()

        # Both fields flow into the checkpointer on the next write
        return {"messages": result.surviving, "conversation_summary": summary}
    ```

    On the following turn, prepend `state["conversation_summary"]` as a system message (or use the reducer's built-in [summary injection](#injecting-the-summary-back-into-messages)) so the model still sees the compressed history.

=== "CrewAI Flow (in a step)"

    ```python
    from crewai.flow.flow import Flow, start, listen
    from crewai.flow.persistence import persist
    from crewai_persistence_cosmosdb import CosmosDBFlowPersistence
    from agentstate_reducer import MessageReducer, ReducerConfig

    reducer = MessageReducer(config=ReducerConfig(
        min_messages=10, max_messages=20, summarize_fn=summarize,
    ))

    @persist(CosmosDBFlowPersistence(
        endpoint=..., database_name="mydb", container_name="flows", key=...,
    ))
    class ChatFlow(Flow):
        @start()
        def handle_turn(self):
            messages = self.state.get("messages", [])
            # ... append the new human/ai turn, call your LLM ...

            result = reducer.reduce(existing=messages)
            summary = self.state.get("conversation_summary", "")
            if result.summary:
                summary = f"{summary}\n{result.summary}".strip()

            # Returned dict becomes the persisted state (summary included)
            return {"messages": result.surviving, "conversation_summary": summary}
    ```

    Here the reducer is run explicitly in the step rather than via the backend's `reducer=` param, so you can capture `result.summary` before the state is written.

!!! tip "Backend `reducer=` vs. manual reduce"
    Passing `reducer=` to a saver/persistence backend prunes **at write time** and keeps only `result.surviving` — it never sees the summary. To persist the summary, run the reducer yourself (as above) and **omit** the backend `reducer=` so pruning isn't applied twice.

### Injecting the summary back into messages

If you'd rather the summary live *inside* the message list (so no separate state field is needed), enable the reducer's summary injection — it inserts the summary as a `human` message plus an `ai` `"OK"` acknowledgement at the point where messages were pruned:

```python
config = ReducerConfig(
    min_messages=10, max_messages=20,
    summarize_fn=summarize,
    inject_summary=True,          # fold the summary into result.surviving itself
)
```

With `inject_summary=True`, `result.surviving` already carries the summary, so the persistence integrations store it automatically — no extra state field or node logic required.

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
