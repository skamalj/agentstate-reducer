"""
Core message reducer — framework-agnostic.

Works with:
- Plain dicts:      {"role": "ai", "content": "...", "id": "..."}
- LangChain types:  AIMessage, HumanMessage, ToolMessage, SystemMessage
- Any object with role/id/tool_calls attributes (duck typing)

Ported from langgraph-reducer's Reducer class with these improvements:
- Works with both LangChain types and plain dicts
- Returns ReducerResult(surviving, pruned, summary) so callers decide
  what to do with pruned messages
- Configurable via ReducerConfig dataclass
- Provides as_langgraph_reducer() bridge for Annotated[list, fn] usage

Preserves original behaviors:
1. Skip index 0 (system message) during pruning
2. When pruning an AIMessage, also prune linked ToolMessages (cascade)
3. Windowed pruning: prune when len > max_messages, keep min_messages
"""

import logging
import threading
from collections import OrderedDict
from typing import Any, List, Optional, Set

from .adapters import get_id, get_role, get_tool_call_id, get_tool_calls
from .models import ReducerConfig, ReducerResult
from .summary import default_summary_messages_factory
from .tokens import resolve_token_counter

logger = logging.getLogger(__name__)


class MessageReducer:
    """
    Framework-agnostic message reducer.

    Concatenates existing + new messages, then prunes oldest messages
    when the total exceeds ``max_messages``, retaining ``min_messages``.

    Pruning rules:
    - Index 0 is preserved (configurable via ``preserve_first``).
    - Only ``ai`` and ``human`` messages are pruned.
    - When an ``ai`` message is pruned, any ``tool`` messages linked to
      it (by ``tool_call_id``) are also pruned (cascade).

    Args:
        min_messages: Number of messages to keep after pruning.
        max_messages: Threshold to trigger pruning. ``None`` disables pruning.
        config:       Optional ``ReducerConfig`` (overrides min/max params).

    Example with plain dicts::

        reducer = MessageReducer(min_messages=5, max_messages=10)
        result = reducer.reduce(
            existing=[{"role": "system", "content": "You are helpful"}],
            new=[{"role": "human", "content": "Hello"}],
        )
        # result.surviving = [...]
        # result.pruned = [...]

    Example with LangChain messages::

        from langchain_core.messages import HumanMessage, AIMessage
        reducer = MessageReducer(min_messages=5, max_messages=10)
        result = reducer.reduce(
            existing=[SystemMessage(content="...")],
            new=[HumanMessage(content="Hello")],
        )
    """

    def __init__(
        self,
        min_messages: int = 0,
        max_messages: Optional[int] = None,
        *,
        config: Optional[ReducerConfig] = None,
    ):
        if config is not None:
            self.config = config
        else:
            self.config = ReducerConfig(
                min_messages=min_messages,
                max_messages=max_messages,
            )
        # on_prune exactly-once bookkeeping: message ids already delivered to hooks.
        self._delivered: "OrderedDict[str, None]" = OrderedDict()
        self._delivered_lock = threading.Lock()

    @property
    def min_messages(self) -> int:
        return self.config.min_messages

    @property
    def max_messages(self) -> Optional[int]:
        return self.config.max_messages

    def _undelivered(self, pruned: List[Any]) -> List[Any]:
        """Filter ``pruned`` to messages not yet handed to on_prune hooks, and record them.

        Messages without an id cannot be tracked and are always returned.
        """
        out: List[Any] = []
        with self._delivered_lock:
            for msg in pruned:
                mid = get_id(msg)
                if mid is None:
                    out.append(msg)
                    continue
                if mid in self._delivered:
                    continue
                self._delivered[mid] = None
                out.append(msg)
            while len(self._delivered) > self.config.dedupe_window:
                self._delivered.popitem(last=False)
        return out

    def _token_window_end(self, messages: List[Any]) -> Optional[int]:
        """
        Compute the exclusive upper bound of the pruning window for token mode.

        Walks messages newest→oldest, keeping the most recent whole messages that
        fit within ``target_tokens`` (defaulting to ``max_tokens``). The preserved
        first message, when enabled, is always retained and its tokens are
        reserved off the top of the budget.

        Returns:
            The index marking the start of the retained recent tail (i.e. the
            ``excess_count`` boundary). Returns ``None`` when the total token
            count is already within ``max_tokens`` and no pruning is required.
        """
        if not messages:
            return None

        counter = resolve_token_counter(self.config.token_counter)
        total_tokens = sum(counter(m) for m in messages)
        if total_tokens <= self.config.max_tokens:
            return None

        start_idx = 1 if self.config.preserve_first else 0
        target = self.config.target_tokens or self.config.max_tokens

        # Reserve tokens for the always-retained first message.
        reserved = counter(messages[0]) if (self.config.preserve_first and messages) else 0
        budget = target - reserved

        # Keep the most recent messages that fit in the remaining budget.
        running = 0
        cut = len(messages)  # default: prune the whole window
        for i in range(len(messages) - 1, start_idx - 1, -1):
            t = counter(messages[i])
            if running + t > budget:
                break
            running += t
            cut = i
        return cut

    def reduce(
        self,
        existing: Optional[List[Any]] = None,
        new: Optional[List[Any]] = None,
        namespace: Any = None,
    ) -> ReducerResult:
        """
        Concatenate existing + new messages, then prune if over threshold.

        Args:
            existing:  Current message list. Defaults to empty list.
            new:       New messages to append. Defaults to empty list.
            namespace: Opaque value forwarded unchanged to every ``on_prune``
                       hook (e.g. a long-term-memory namespace). The reducer
                       never inspects it. Defaults to None.

        Returns:
            ``ReducerResult`` with surviving messages, pruned messages,
            and optional summary.
        """
        if existing is None:
            existing = []
        if new is None:
            new = []

        messages = list(existing) + list(new)
        start_idx = 1 if self.config.preserve_first else 0

        # ── Determine the pruning window [start_idx, excess_count) ──
        # Token-budget mode takes precedence over message-count mode.
        if self.config.max_tokens is not None:
            excess_count = self._token_window_end(messages)
            # No pruning needed if total is already within budget.
            if excess_count is None:
                return ReducerResult(surviving=messages, pruned=[])
        else:
            max_msgs = self.config.max_messages
            if max_msgs is None or len(messages) <= max_msgs:
                return ReducerResult(surviving=messages, pruned=[])
            excess_count = len(messages) - self.config.min_messages

        # ── Identify indices to prune ──
        to_delete: Set[int] = set()

        # Iterate over the pruning window: from start_idx to excess_count
        for i, msg in enumerate(messages[start_idx:excess_count], start=start_idx):
            role = get_role(msg)

            if role in ("ai", "human"):
                to_delete.add(i)

            # ToolMessage cascade: when pruning an AIMessage, also prune
            # any ToolMessages that reference its tool_call IDs
            if role == "ai" and self.config.cascade_tool_messages:
                for tc in get_tool_calls(messages[i]):
                    tc_id = (
                        tc.get("id")
                        if isinstance(tc, dict)
                        else getattr(tc, "id", None)
                    )
                    if tc_id is None:
                        continue
                    for j in range(i + 1, len(messages)):
                        if (
                            get_role(messages[j]) == "tool"
                            and get_tool_call_id(messages[j]) == tc_id
                        ):
                            to_delete.add(j)

        # ── Split into surviving and pruned ──
        pruned = [messages[i] for i in sorted(to_delete)]
        surviving = [msg for i, msg in enumerate(messages) if i not in to_delete]

        logger.debug(
            "Reduced messages from %d to %d (pruned %d)",
            len(messages),
            len(surviving),
            len(pruned),
        )

        # ── Optional summarization (+ optional injection) ──
        # The summary is always returned on the result. A previously injected
        # summary block is an ordinary human/ai pair at the front of the window,
        # so it is naturally included in `pruned` and rolled into the new summary
        # here — no marker/replacement bookkeeping needed.
        summary = None
        if pruned and self.config.summarize_fn is not None:
            try:
                summary = self.config.summarize_fn(pruned)
            except Exception as exc:
                logger.warning("Summarization failed: %s", exc)

            # Inject the summary block in place of the pruned messages: after any
            # preserved-first messages, immediately before the retained recent tail.
            if summary is not None and self.config.inject_summary:
                factory = self.config.summary_message_factory or default_summary_messages_factory
                first_pruned = min(to_delete)
                insert_pos = sum(1 for i in range(first_pruned) if i not in to_delete)
                block = factory(summary, len(pruned))
                surviving[insert_pos:insert_pos] = block

        # ── on_prune hooks: hand the pruned messages to long-term memory ──
        if pruned and self.config.on_prune:
            to_deliver = self._undelivered(pruned) if self.config.dedupe_on_prune else pruned
            if to_deliver:
                for hook in self.config.on_prune:
                    try:
                        hook(to_deliver, namespace)
                    except Exception as exc:
                        logger.warning("on_prune hook %r failed: %s", hook, exc)

        return ReducerResult(
            surviving=surviving,
            pruned=pruned,
            summary=summary,
        )

    def as_langgraph_reducer(self):
        """
        Return a function compatible with LangGraph's ``Annotated[list, fn]`` pattern.

        The returned function has the signature ``(existing, new) -> merged_list``
        which is what LangGraph expects for a custom reducer annotated on a
        state field.

        Usage::

            reducer = MessageReducer(min_messages=10, max_messages=20)

            class MyState(TypedDict):
                messages: Annotated[list, reducer.as_langgraph_reducer()]

        This is the bridge that lets ``PrunableStateFactory`` keep working
        unchanged when migrating from ``langgraph-reducer``.
        """

        def _reduce(existing=None, new=None):
            if existing is None:
                existing = []
            result = self.reduce(existing, new)
            return result.surviving

        return _reduce

    def __repr__(self) -> str:
        if self.config.max_tokens is not None:
            return (
                f"MessageReducer(max_tokens={self.config.max_tokens}, "
                f"target_tokens={self.config.target_tokens or self.config.max_tokens}, "
                f"preserve_first={self.config.preserve_first}, "
                f"cascade_tool_messages={self.config.cascade_tool_messages})"
            )
        return (
            f"MessageReducer(min_messages={self.config.min_messages}, "
            f"max_messages={self.config.max_messages}, "
            f"preserve_first={self.config.preserve_first}, "
            f"cascade_tool_messages={self.config.cascade_tool_messages})"
        )
