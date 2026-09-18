"""
Helpers for ``ReducerConfig.on_prune`` hooks.

``Background`` wraps any ``RememberFn`` so it runs on a small worker pool
instead of inside the caller's ``reduce()`` (which, in a checkpointer, is on
the request path). Use it when the hook does something slow, e.g. calls an
LLM to extract facts before writing to a memory store.

    on_prune=[Background(remember)]     # slow hook, off the request path
    on_prune=[remember]                 # cheap hook, inline

Behaviour baked in so callers don't have to think about it:

- The pruned list is copied before it is handed to the worker, so later
  mutation by the caller cannot race the hook.
- The backlog is bounded (``max_pending``). When the pool falls too far
  behind, new batches are dropped with a warning rather than blocking the
  request or growing memory without limit.
- Pending work is drained at interpreter exit via ``atexit``. On serverless
  runtimes that freeze the process after the response (e.g. AWS Lambda) call
  ``close()`` at the end of the handler, or use the inline form.
"""

import atexit
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, List

from .models import RememberFn

logger = logging.getLogger(__name__)


class Background:
    """Run a ``RememberFn`` off the request path on a bounded worker pool."""

    def __init__(self, fn: RememberFn, *, workers: int = 2, max_pending: int = 1000) -> None:
        if workers < 1:
            raise ValueError("Background: workers must be >= 1")
        if max_pending < 1:
            raise ValueError("Background: max_pending must be >= 1")
        self._fn = fn
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="on_prune")
        self._slots = threading.BoundedSemaphore(max_pending)
        self._closed = False
        self.dropped = 0
        atexit.register(self.close)

    def __call__(self, pruned: List[Any], namespace: Any) -> None:
        if self._closed:
            logger.warning("Background: hook called after close(); dropping batch")
            self.dropped += 1
            return
        if not self._slots.acquire(blocking=False):
            logger.warning("Background: on_prune backlog full; dropping batch of %d", len(pruned))
            self.dropped += 1
            return
        try:
            fut = self._pool.submit(self._fn, list(pruned), namespace)
        except RuntimeError:  # pool shut down concurrently
            self._slots.release()
            self.dropped += 1
            return
        fut.add_done_callback(self._done)

    def _done(self, fut: Future) -> None:
        self._slots.release()
        exc = fut.exception()
        if exc is not None:
            logger.warning("Background: on_prune hook %r failed: %s", self._fn, exc)

    def close(self, wait: bool = True) -> None:
        """Stop accepting work and (by default) wait for queued batches to finish."""
        if self._closed:
            return
        self._closed = True
        self._pool.shutdown(wait=wait)

    def __enter__(self) -> "Background":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
