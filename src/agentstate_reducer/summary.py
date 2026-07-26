"""
Helpers for the optional summary-injection feature.

When ``ReducerConfig.inject_summary`` is enabled and pruning produces a summary,
the reducer inserts summary messages into the surviving list, at the position the
pruned messages occupied (after any preserved-first messages, immediately before
the retained recent tail).

To keep the conversation well-formed for providers that require strict role
alternation, the default injects a **pair**: a ``human`` message carrying the
summary followed by a short ``ai`` acknowledgement ("OK"). This makes the
injected block a self-contained ``human -> ai`` exchange:

    [system] -> [human: summary] -> [ai: OK] -> [recent tail]

Both injected messages are ordinary ``human``/``ai`` messages sitting at the
front of the prunable window, so on the next reduction they are pruned and
rolled into the new summary automatically — there is exactly one summary pair at
any time, with no marker/replacement bookkeeping required.
"""

from typing import Any, List


def default_summary_messages_factory(text: str, count: int) -> List[Any]:
    """Build the default injected summary block: a human summary + an ai ack.

    Args:
        text:  The summary string produced by ``summarize_fn``.
        count: Number of messages that were summarized (for the human phrasing).

    Returns:
        A list of message dicts to insert at the pruned slot.
    """
    return [
        {"role": "human", "content": f"Here is the summary of previous {count} messages: {text}"},
        {"role": "ai", "content": "OK"},
    ]
