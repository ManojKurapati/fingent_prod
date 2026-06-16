"""An in-memory fake connector for tests.

Exposes a tiny key/value store with a non-consequential ``kv_read`` tool and
consequential ``kv_write`` / ``kv_delete`` tools, so guardrail and orchestration
tests have something concrete to exercise without real external systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from app.connectors.base import Tool, ToolRegistry


@dataclass
class FakeStore:
    """A trivial in-memory key/value store shared by the fake connector's tools."""

    data: dict[str, str] = field(default_factory=dict)


class WritePayload(TypedDict):
    key: str
    value: str


class _KvRead(Tool[str, "str | None"]):
    name = "kv_read"
    consequential = False

    def __init__(self, store: FakeStore) -> None:
        self._store = store

    async def invoke(self, payload: str) -> str | None:
        return self._store.data.get(payload)


class _KvWrite(Tool[WritePayload, None]):
    name = "kv_write"
    consequential = True  # a write is a consequential action

    def __init__(self, store: FakeStore) -> None:
        self._store = store

    async def invoke(self, payload: WritePayload) -> None:
        self._store.data[payload["key"]] = payload["value"]


class _KvDelete(Tool[str, bool]):
    name = "kv_delete"
    consequential = True

    def __init__(self, store: FakeStore) -> None:
        self._store = store

    async def invoke(self, payload: str) -> bool:
        return self._store.data.pop(payload, None) is not None


def build_fake_connector(*, store: FakeStore | None = None) -> ToolRegistry:
    """Build a registry wired to a (possibly shared) :class:`FakeStore`."""
    store = store or FakeStore()
    registry = ToolRegistry()
    registry.register(_KvRead(store))
    registry.register(_KvWrite(store))
    registry.register(_KvDelete(store))
    return registry
