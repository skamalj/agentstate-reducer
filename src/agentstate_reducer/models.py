"""
Shared data models for the agentstate-reducer package.

These are framework-agnostic — no imports from langchain, crewai, etc.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

# A prune hook: called with (pruned_messages, namespace) whenever a reduce()
# call prunes at least one message. ``namespace`` is whatever the caller of
# reduce() forwarded (a LangGraph store namespace tuple, a user id, ...) or
# None when the caller did not supply one. The reducer never inspects it.
RememberFn = Callable[[List[Any], Any], Any]

DEFAULT_NAMESPACE_KEY = "memory_namespace"


@dataclass
class ReducerConfig:
    """
    Configuration for the MessageReducer.

    Pruning operates in one of two modes:

    - **Message-count mode** (default): pruning triggers when the number of
      messages exceeds ``max_messages``, retaining ``min_messages``.
    - **Token-budget mode**: when ``max_tokens`` is set, pruning triggers when
      the estimated total token count exceeds ``max_tokens``, retaining the most
      recent whole messages until the total is at or below ``target_tokens``
      (defaults to ``max_tokens``). Messages are never truncated — only whole
      messages are dropped. Token mode takes precedence over message-count mode.

    Attributes:
        min_messages:          Number of messages to retain after pruning
                               (message-count mode).
        max_messages:          Pruning triggers when message count exceeds this.
                               Set to None to disable count-based pruning.
        max_tokens:            Pruning triggers when the estimated total token
                               count exceeds this. Set to None (default) to use
                               message-count mode instead.
        target_tokens:         Prune down to at or below this token count. When
                               None, defaults to ``max_tokens``. Set lower than
                               ``max_tokens`` to create hysteresis (e.g. prune at
                               4000, down to 2000).
        token_counter:         Optional callable(message) -> int. When provided,
                               used to count tokens per message. When omitted,
                               tiktoken is used if installed, otherwise a
                               character-based heuristic.
        preserve_first:        If True, index 0 is never pruned (system message).
        cascade_tool_messages: If True, when an AIMessage is pruned, also prune
                               any ToolMessages linked to it via tool_call_id.
        summarize_fn:          Optional callable(pruned_messages) -> str.
                               Called with the list of pruned messages so you can
                               generate a summary (e.g., via LLM) of what was removed.
                               The summary is always returned on ReducerResult.summary.
        inject_summary:        If True, the generated summary is also inserted into
                               the surviving messages, in place of the pruned block
                               (after preserve_first, before the retained recent tail).
                               Requires summarize_fn. The default injection is a
                               human summary + an ai "OK" acknowledgement pair; because
                               these are ordinary human/ai messages at the front of the
                               window, the next prune rolls them into the new summary —
                               so there is always exactly one summary block, with no
                               accumulation. Providers requiring strict role alternation
                               are handled by the human->ai pair; override
                               summary_message_factory for other shapes.
        summary_message_factory:
                               Optional callable(summary_text, pruned_count) -> list of
                               messages. Builds the injected summary block. Defaults to
                               a [human summary, ai "OK"] pair. Return a single-element
                               list to inject just one message.
        on_prune:              Optional list of ``RememberFn`` callables
                               ``(pruned_messages, namespace) -> Any``. Each is
                               invoked (in order) after pruning, with the pruned
                               messages and the ``namespace`` passed to
                               ``reduce()``. Use this to hand messages leaving
                               the context window to a long-term memory store.
                               Hooks run synchronously; wrap an expensive hook
                               in ``agentstate_reducer.Background`` to run it
                               off the request path. A hook that raises is
                               logged and skipped; it never breaks the reduce.
        namespace_key:         The key that framework integrations (checkpointers,
                               persistence layers) look up in their per-call
                               config / state to find the memory namespace to
                               forward to ``reduce(namespace=...)``. Defaults to
                               ``"memory_namespace"``. The reducer itself never
                               reads it; it is published here so every
                               integration agrees on one name.
        dedupe_on_prune:       If True (default), a message is handed to the
                               ``on_prune`` hooks at most once per reducer
                               instance, keyed by message id. Persistence layers
                               commonly call ``reduce()`` several times per turn
                               on overlapping message lists (e.g. LangGraph
                               writes a checkpoint per super-step), which would
                               otherwise deliver the same pruned message to the
                               hooks repeatedly. Messages without an id are
                               always delivered. Set False to receive every
                               prune verbatim.
        dedupe_window:         How many recently-delivered message ids to remember
                               for ``dedupe_on_prune`` (bounded, oldest evicted).
    """

    min_messages: int = 10
    max_messages: Optional[int] = 20
    max_tokens: Optional[int] = None
    target_tokens: Optional[int] = None
    token_counter: Optional[Callable[[Any], int]] = None
    preserve_first: bool = True
    cascade_tool_messages: bool = True
    summarize_fn: Optional[Callable[[List[Any]], str]] = None
    inject_summary: bool = False
    summary_message_factory: Optional[Callable[[str, int], List[Any]]] = None
    on_prune: List[RememberFn] = field(default_factory=list)
    namespace_key: str = DEFAULT_NAMESPACE_KEY
    dedupe_on_prune: bool = True
    dedupe_window: int = 10_000


@dataclass
class ReducerResult:
    """
    Output of a reduce operation.

    Both downstream consumers need to know what survived AND what was pruned:
    - langgraph-checkpoint-cosmosdb: stores `surviving`, may log `pruned`
    - crewai-persistence-cosmosdb:   stores `surviving`, may call summarize on `pruned`

    Attributes:
        surviving: Messages that remain after pruning.
        pruned:    Messages that were removed.
        summary:   If a summarize_fn was configured and pruning occurred,
                   this contains the summary string.
    """

    surviving: List[Any] = field(default_factory=list)
    pruned: List[Any] = field(default_factory=list)
    summary: Optional[str] = None
