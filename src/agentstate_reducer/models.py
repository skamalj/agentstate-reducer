"""
Shared data models for the agentstate-reducer package.

These are framework-agnostic — no imports from langchain, crewai, etc.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional


@dataclass
class ReducerConfig:
    """
    Configuration for the MessageReducer.

    Attributes:
        min_messages:          Number of messages to retain after pruning.
        max_messages:          Pruning triggers when message count exceeds this.
                               Set to None to disable pruning.
        preserve_first:        If True, index 0 is never pruned (system message).
        cascade_tool_messages: If True, when an AIMessage is pruned, also prune
                               any ToolMessages linked to it via tool_call_id.
        summarize_fn:          Optional callable(pruned_messages) -> str.
                               Called with the list of pruned messages so you can
                               generate a summary (e.g., via LLM) of what was removed.
    """

    min_messages: int = 10
    max_messages: Optional[int] = 20
    preserve_first: bool = True
    cascade_tool_messages: bool = True
    summarize_fn: Optional[Callable[[List[Any]], str]] = None


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
