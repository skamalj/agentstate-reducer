"""``ReducingSaver``: run a ``MessageReducer`` inside any LangGraph checkpointer's save path.

LangGraph stores the whole message channel in every checkpoint, so a thread's
storage grows with the square of its length: turn *n* writes a blob holding
all *n* messages. Pruning old checkpoints (``prune``, ``delete_thread``, TTL)
removes old versions but never shrinks the latest one. ``ReducingSaver`` bounds
that axis: it applies the reducer to the ``messages`` channel just before each
checkpoint is written, so every blob holds at most ``max_messages`` messages,
and the pruned turns reach the reducer's ``on_prune`` hooks exactly once, with
the ``memory_namespace`` from the run config.

    from agentstate_reducer import MessageReducer, ReducerConfig
    from agentstate_reducer.langgraph import ReducingSaver

    saver = ReducingSaver(PostgresSaver.from_conn_string(url), MessageReducer(config=ReducerConfig(max_messages=20)))
    graph = builder.compile(checkpointer=saver)

Behaviour with savers that already know about the reducer (``langgraph-dynamodb-checkpoint``,
``langgraph-checkpoint-cosmosdb``, ``langgraph-checkpoint-firestore``, or another
``ReducingSaver``), decided once in the constructor:

* inner has no ``reducer`` attribute: the wrapper reduces in ``put`` / ``aput``;
* inner has ``reducer`` set to ``None``: the wrapper assigns its reducer to the
  inner saver and becomes a pure pass-through (``passthrough`` is ``True``);
* inner already holds the same reducer object: pass-through;
* inner holds a different reducer: ``ValueError``. Two reducers keep two
  dedupe memories, so pruned turns would reach long-term memory twice.

The wrapper delegates everything else to the inner saver, including the
optional capabilities (``copy_thread``, ``delete_for_runs``, ``prune``, delta
channel history) when, and only when, the inner saver implements them, so
LangGraph's capability probing and the conformance suite see the inner saver's
true capabilities.

This module imports ``langgraph.checkpoint`` and is therefore optional:
``pip install "agentstate-reducer[langgraph]"``. The core package stays
dependency-free.

Caveat: the reducer replaces the channel value wholesale. Do not use it on a
messages channel backed by ``DeltaChannel``.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver

from .models import DEFAULT_NAMESPACE_KEY

logger = logging.getLogger("agentstate_reducer.langgraph")

__all__ = ["ReducingSaver", "memory_namespace", "apply_reducer"]


def memory_namespace(reducer: Any, config: Optional[Dict[str, Any]]) -> Any:
    """Resolve the long-term-memory namespace forwarded to ``on_prune`` hooks.

    Looks up ``reducer.config.namespace_key`` (default ``"memory_namespace"``)
    in ``config["configurable"]``. Falls back to ``("memories", thread_id)``
    so apps that never set it still get per-thread memory, and to ``None``
    when there is no thread either. Same rule as the agentstate checkpointers.
    """
    conf = (config or {}).get("configurable", {}) or {}
    key = getattr(getattr(reducer, "config", None), "namespace_key", DEFAULT_NAMESPACE_KEY)
    ns = conf.get(key)
    if ns is not None:
        return ns
    thread_id = conf.get("thread_id")
    return ("memories", thread_id) if thread_id is not None else None


def apply_reducer(reducer: Any, checkpoint: Dict[str, Any], config: Optional[Dict[str, Any]], messages_key: str = "messages") -> Dict[str, Any]:
    """Return a shallow copy of ``checkpoint`` whose ``messages_key`` channel has been reduced.

    Non-mutating. Returns the original checkpoint when there is no reducer or
    no message list. The pruned messages are delivered to the reducer's
    ``on_prune`` hooks with the namespace from ``memory_namespace``.
    """
    if reducer is None:
        return checkpoint
    channel_values = checkpoint.get("channel_values") or {}
    messages = channel_values.get(messages_key)
    if not messages:
        return checkpoint
    result = reducer.reduce(existing=messages, new=[], namespace=memory_namespace(reducer, config))
    if len(result.surviving) == len(messages):
        return checkpoint
    new_values = dict(channel_values)
    new_values[messages_key] = result.surviving
    new_checkpoint = copy.copy(checkpoint)
    new_checkpoint["channel_values"] = new_values
    return new_checkpoint


# Methods that BaseCheckpointSaver treats as optional capabilities. They are
# added to the wrapper class only when the inner saver overrides them.
_OPTIONAL_METHODS = (
    "copy_thread", "acopy_thread",
    "delete_for_runs", "adelete_for_runs",
    "prune", "aprune",
    "get_delta_channel_history", "aget_delta_channel_history",
)

_specialized_classes: Dict[type, type] = {}


def _delegate(name: str):
    def method(self, *args, **kwargs):
        return getattr(self.inner, name)(*args, **kwargs)
    method.__name__ = name
    method.__doc__ = f"Delegates to ``inner.{name}``."
    return method


def _async_delegate(name: str):
    async def method(self, *args, **kwargs):
        return await getattr(self.inner, name)(*args, **kwargs)
    method.__name__ = name
    method.__doc__ = f"Delegates to ``inner.{name}``."
    return method


def _is_overridden(inner_type: type, name: str) -> bool:
    base = getattr(BaseCheckpointSaver, name, None)
    impl = getattr(inner_type, name, None)
    if base is None or impl is None:
        return impl is not None
    return impl is not base


def _specialized(inner_type: type) -> type:
    """A ``ReducingSaver`` subclass exposing exactly the optional methods ``inner_type`` implements."""
    cls = _specialized_classes.get(inner_type)
    if cls is None:
        attrs = {}
        for name in _OPTIONAL_METHODS:
            if _is_overridden(inner_type, name):
                attrs[name] = _async_delegate(name) if name.startswith("a") else _delegate(name)
        attrs["__module__"] = __name__
        attrs["__doc__"] = f"ReducingSaver around {inner_type.__name__}."
        cls = type(f"ReducingSaver[{inner_type.__name__}]", (ReducingSaver,), attrs)
        _specialized_classes[inner_type] = cls
    return cls


class ReducingSaver(BaseCheckpointSaver):
    """Apply a ``MessageReducer`` to the messages channel before any checkpointer stores it.

    Args:
        inner:        Any ``BaseCheckpointSaver``.
        reducer:      A ``MessageReducer``.
        messages_key: State channel holding the message list. Default ``"messages"``.

    Attributes:
        inner:        The wrapped saver.
        reducer:      The reducer in force (on this wrapper or, in pass-through mode, on the inner saver).
        passthrough:  ``True`` when the inner saver applies the reducer itself and this wrapper only delegates.
    """

    def __new__(cls, inner: BaseCheckpointSaver, *args: Any, **kwargs: Any):
        if cls is ReducingSaver:
            cls = _specialized(type(inner))
        return super().__new__(cls)

    def __init__(self, inner: BaseCheckpointSaver, reducer: Any, *, messages_key: str = "messages") -> None:
        if reducer is None:
            raise ValueError("ReducingSaver needs a reducer; pass the inner saver directly if you do not want one")
        super().__init__(serde=inner.serde)
        self.inner = inner
        self.messages_key = messages_key
        self.passthrough = False
        existing = getattr(inner, "reducer", _MISSING)
        if existing is _MISSING:
            self.reducer = reducer
        elif existing is None:
            inner.reducer = reducer
            self.reducer = reducer
            self.passthrough = True
            logger.debug("%s applies the reducer itself; ReducingSaver is a pass-through", type(inner).__name__)
        elif existing is reducer:
            self.reducer = reducer
            self.passthrough = True
        else:
            raise ValueError(
                f"{type(inner).__name__} already has a different reducer; wrapping it would deliver "
                "pruned messages to on_prune hooks twice. Pass reducer= to the saver instead."
            )

    # -- reduction happens here --------------------------------------------------

    def _reduced(self, checkpoint: Dict[str, Any], config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if self.passthrough:
            return checkpoint
        return apply_reducer(self.reducer, checkpoint, config, self.messages_key)

    def put(self, config, checkpoint, metadata, new_versions):
        return self.inner.put(config, self._reduced(checkpoint, config), metadata, new_versions)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await self.inner.aput(config, self._reduced(checkpoint, config), metadata, new_versions)

    # -- everything else is delegated ----------------------------------------------

    @property
    def config_specs(self):
        return self.inner.config_specs

    def get_next_version(self, current, channel):
        return self.inner.get_next_version(current, channel)

    def get(self, config):
        return self.inner.get(config)

    def get_tuple(self, config):
        return self.inner.get_tuple(config)

    def list(self, config, *, filter=None, before=None, limit=None):
        return self.inner.list(config, filter=filter, before=before, limit=limit)

    def put_writes(self, config, writes, task_id, task_path=""):
        return self.inner.put_writes(config, writes, task_id, task_path)

    def delete_thread(self, thread_id):
        return self.inner.delete_thread(thread_id)

    async def aget(self, config):
        return await self.inner.aget(config)

    async def aget_tuple(self, config):
        return await self.inner.aget_tuple(config)

    def alist(self, config, *, filter=None, before=None, limit=None):
        return self.inner.alist(config, filter=filter, before=before, limit=limit)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        return await self.inner.aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id):
        return await self.inner.adelete_thread(thread_id)

    def __getattr__(self, name: str) -> Any:
        # Anything not defined here (backend-specific helpers, setup(), ...) comes from the inner saver.
        if name in ("inner", "reducer", "passthrough", "messages_key"):
            raise AttributeError(name)
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        mode = "passthrough" if self.passthrough else "reducing"
        return f"ReducingSaver({self.inner!r}, {mode})"


_MISSING = object()
