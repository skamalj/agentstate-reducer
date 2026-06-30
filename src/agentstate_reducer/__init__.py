"""
agentstate-reducer: Framework-agnostic message reducer for AI agent state management.

Works with LangGraph, CrewAI, and plain dicts.
"""

from .models import ReducerConfig, ReducerResult
from .reducer import MessageReducer
from .tokens import resolve_token_counter

__all__ = [
    "MessageReducer",
    "ReducerConfig",
    "ReducerResult",
    "resolve_token_counter",
]
