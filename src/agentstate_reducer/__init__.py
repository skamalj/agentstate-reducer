"""
agentstate-reducer: Framework-agnostic message reducer for AI agent state management.

Works with LangGraph, CrewAI, and plain dicts.
"""

from .models import ReducerConfig, ReducerResult
from .reducer import MessageReducer

__all__ = [
    "MessageReducer",
    "ReducerConfig",
    "ReducerResult",
]
