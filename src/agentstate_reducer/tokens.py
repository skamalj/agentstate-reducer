"""
Token counting for message pruning — framework-agnostic, dependency-free core.

Resolution order for counting tokens of a message (highest priority first):

1. A user-supplied ``token_counter`` callable on the ReducerConfig.
2. ``tiktoken`` if it is installed (accurate for OpenAI-family models).
3. A character-based heuristic (``len(content) / CHARS_PER_TOKEN``) — rough but
   dependency-free, fine for "approximately N tokens" windowing.

Only message *content* is counted. A small per-message overhead is added to
approximate role/formatting tokens, matching how chat models frame messages.
"""

import logging
from typing import Any, Callable, Optional

from .adapters import get_content

logger = logging.getLogger(__name__)

# Heuristic: English text averages ~4 characters per token.
CHARS_PER_TOKEN = 4

# Per-message overhead (role tag + message framing), approximated from the
# OpenAI chat format (~4 tokens per message).
PER_MESSAGE_OVERHEAD = 4

# Cached tiktoken encoding — resolved lazily on first use.
_TIKTOKEN_ENCODING = None
_TIKTOKEN_TRIED = False


def _get_tiktoken_encoding():
    """Return a cached tiktoken encoding, or None if tiktoken is unavailable."""
    global _TIKTOKEN_ENCODING, _TIKTOKEN_TRIED
    if _TIKTOKEN_TRIED:
        return _TIKTOKEN_ENCODING
    _TIKTOKEN_TRIED = True
    try:
        import tiktoken

        _TIKTOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - import/availability dependent
        _TIKTOKEN_ENCODING = None
    return _TIKTOKEN_ENCODING


def _heuristic_count(text: str) -> int:
    """Character-based token estimate."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def resolve_token_counter(
    token_counter: Optional[Callable[[Any], int]] = None,
) -> Callable[[Any], int]:
    """
    Return a callable ``(message) -> int`` that counts tokens for one message.

    Layered resolution:
    1. If ``token_counter`` is provided, use it as-is.
    2. Else if tiktoken is importable, encode the message content with it.
    3. Else use the character heuristic.

    A per-message overhead is added on top of the content count for the built-in
    counters (2 and 3); a user-supplied counter is trusted to do its own thing.
    """
    if token_counter is not None:
        return token_counter

    encoding = _get_tiktoken_encoding()
    if encoding is not None:
        def _tiktoken_counter(msg: Any) -> int:
            content = get_content(msg) or ""
            if not isinstance(content, str):
                content = str(content)
            return len(encoding.encode(content)) + PER_MESSAGE_OVERHEAD

        return _tiktoken_counter

    def _heuristic_counter(msg: Any) -> int:
        content = get_content(msg) or ""
        if not isinstance(content, str):
            content = str(content)
        return _heuristic_count(content) + PER_MESSAGE_OVERHEAD

    return _heuristic_counter
