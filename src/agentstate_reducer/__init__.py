"""
agentstate-reducer: Framework-agnostic message reducer for AI agent state management.

Works with LangGraph, CrewAI, and plain dicts.
"""

from .hooks import Background
from .models import DEFAULT_NAMESPACE_KEY, ReducerConfig, ReducerResult, RememberFn
from .reducer import MessageReducer
from .summary import default_summary_messages_factory
from .tokens import resolve_token_counter

__all__ = [
    "MessageReducer",
    "ReducerConfig",
    "ReducerResult",
    "RememberFn",
    "Background",
    "DEFAULT_NAMESPACE_KEY",
    "resolve_token_counter",
    "default_summary_messages_factory",
]
