"""Bounded, idempotent parallel fan-out.

The core runner launches every ready step at once, which is correct for a handful
of subagents. A load-bearing fan-out (e.g. variance across hundreds of cost
centres) needs two extra guarantees:

* **Bounded concurrency** — never run more than ``limit`` effects at once, so a
  burst cannot exhaust connectors / rate limits / memory.
* **No double-execution under retries** — an item whose effect already *committed*
  is never executed again when the surrounding job is retried (idempotency by key,
  on top of the queue's at-least-once delivery).

Both are needed for the platform's "no double-posting / double-trading" promise to
hold even when work is sharded across a large fan-out.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

# An effect: given an item's payload, perform its work and return a result.
Effect = Callable[[Any], Awaitable[Any]]
# An optional per-task hook run inside the concurrency slot (tests use it to
# coordinate; production leaves it unset).
Hook = Callable[[], Awaitable[None]]


class BoundedFanout:
    """Run keyed effects with bounded concurrency and idempotent commit tracking.

    ``done`` and ``committed`` may be shared across retries of the same job so that
    a re-run skips already-committed items. An effect that raises is *not* marked
    done (so it is legitimately retried), but a committed item never runs twice.
    """

    def __init__(
        self,
        *,
        limit: int,
        done: set[str] | None = None,
        committed: list[str] | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self._limit = limit
        self._sem = asyncio.Semaphore(limit)
        self._active = 0
        self.peak_concurrency = 0
        self._done = done if done is not None else set()
        self._committed = committed if committed is not None else []

    @property
    def committed(self) -> list[str]:
        """Keys committed exactly once, in commit order (deduplicated by design)."""
        return list(self._committed)

    async def run(
        self,
        items: list[tuple[str, Any]],
        effect: Effect,
        *,
        before: Hook | None = None,
    ) -> list[Any]:
        """Run ``effect`` for each ``(key, payload)`` with at most ``limit`` in flight.

        Returns results in item order (``None`` for items skipped as already done).
        """

        async def _one(key: str, payload: Any) -> Any:
            async with self._sem:
                self._active += 1
                self.peak_concurrency = max(self.peak_concurrency, self._active)
                try:
                    if before is not None:
                        await before()
                    if key in self._done:
                        return None
                    result = await effect(payload)
                    self._committed.append(key)
                    self._done.add(key)
                    return result
                finally:
                    self._active -= 1

        return await asyncio.gather(*(_one(key, payload) for key, payload in items))
