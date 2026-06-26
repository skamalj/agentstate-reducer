"""
Adapters for extracting fields from messages in a framework-agnostic way.

Works with:
- Plain dicts:  {"role": "ai", "content": "...", "id": "...", "tool_calls": [...]}
- LangChain BaseMessage subclasses: AIMessage, HumanMessage, ToolMessage, etc.
- Any object with the expected attributes (duck typing)

This module does NOT import langchain_core. It uses duck typing and class-name
inspection so the package remains zero-dependency.
"""

from typing import Any, Dict, List, Optional


# ── Role mapping from LangChain class names ──

_CLASS_NAME_TO_ROLE = {
    "human": "human",
    "humanmessage": "human",
    "ai": "ai",
    "aimessage": "ai",
    "agent": "ai",          # LangGraph task outputs and some frameworks use "agent"
    "agentmessage": "ai",
    "tool": "tool",
    "toolmessage": "tool",
    "system": "system",
    "systemmessage": "system",
    "function": "function",
    "functionmessage": "function",
    "chatmessage": "chat",
}

# Aliases used by OpenAI-compatible APIs and some agent frameworks
_ROLE_ALIASES = {
    "user": "human",
    "agent": "ai",
    "assistant": "ai",
}


def get_role(msg: Any) -> str:
    """
    Extract the role/type from a message.

    Handles:
    - dict with "role" key:  {"role": "ai", ...}
    - dict with "type" key:  {"type": "ai", ...}  (LangChain serialized format)
    - LangChain BaseMessage: uses class name → role mapping
    - Any object with a .type attribute

    Returns:
        Lowercase role string: "human", "ai", "tool", "system", etc.
    """
    if isinstance(msg, dict):
        raw = (msg.get("role") or msg.get("type") or "").lower()
        return _ROLE_ALIASES.get(raw, raw)

    # Try class name mapping (covers all LangChain message types)
    class_name = type(msg).__name__.lower()
    role = _CLASS_NAME_TO_ROLE.get(class_name)
    if role:
        return role

    # Fallback: .type attribute (LangChain BaseMessage has this)
    raw = getattr(msg, "type", "unknown").lower()
    return _ROLE_ALIASES.get(raw, raw)


def get_id(msg: Any) -> Optional[str]:
    """
    Extract the unique message ID.

    Handles:
    - dict: msg["id"]
    - Object: msg.id
    """
    if isinstance(msg, dict):
        return msg.get("id")
    return getattr(msg, "id", None)


def get_content(msg: Any) -> str:
    """
    Extract message content.

    Handles:
    - dict: msg["content"]
    - Object: msg.content
    """
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", "")


def get_tool_calls(msg: Any) -> List[Dict]:
    """
    Extract tool_calls from an AI message.

    Handles:
    - dict: msg["tool_calls"] → list of dicts
    - LangChain AIMessage: msg.tool_calls → list of ToolCall objects or dicts

    Returns:
        List of dicts with at least {"id": ...} for each tool call.
        Returns empty list if no tool_calls found.
    """
    if isinstance(msg, dict):
        return msg.get("tool_calls", [])

    raw = getattr(msg, "tool_calls", [])
    if not raw:
        return []

    result = []
    for tc in raw:
        if isinstance(tc, dict):
            result.append(tc)
        else:
            # LangChain ToolCall object → convert to dict
            result.append({
                "id": getattr(tc, "id", None),
                "name": getattr(tc, "name", None),
                "args": getattr(tc, "args", {}),
            })
    return result


def get_tool_call_id(msg: Any) -> Optional[str]:
    """
    Extract tool_call_id from a ToolMessage.

    Handles:
    - dict: msg["tool_call_id"]
    - LangChain ToolMessage: msg.tool_call_id
    """
    if isinstance(msg, dict):
        return msg.get("tool_call_id")
    return getattr(msg, "tool_call_id", None)
