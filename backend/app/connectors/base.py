"""Typed Tool / connector interface — FROZEN CONTRACT.

Every external capability an agent can use (ERP/GL, bank APIs, market data, CRM,
filings) is exposed as a typed :class:`Tool`. A tool declares whether it performs
a **consequential action** (posts to a ledger, moves cash, binds risk, lends,
files/communicates externally). The guardrail engine inspects ``consequential``
to decide whether a call must be gated behind human approval.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator


class Tool[I, O](ABC):
    """A single typed capability.

    Subclasses set ``name`` (unique within a registry) and ``consequential``
    (defaults to ``False``), and implement :meth:`invoke`.
    """

    name: str
    consequential: bool = False

    @abstractmethod
    async def invoke(self, payload: I) -> O:
        """Perform the tool's action and return its typed result."""
        raise NotImplementedError


class ToolNotFoundError(KeyError):
    """Raised when a tool name is not present in a registry."""


class ToolRegistry:
    """A named collection of tools — the unit a connector exposes to agents."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool[object, object]] = {}

    def register[I, O](self, tool: Tool[I, O]) -> Tool[I, O]:
        """Register ``tool`` and return it. Names must be unique."""
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool  # type: ignore[assignment]
        return tool

    def get(self, name: str) -> Tool[object, object]:
        """Fetch a tool by name, raising :class:`ToolNotFoundError` if absent."""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(name) from exc

    def all(self) -> list[Tool[object, object]]:
        """All registered tools, in registration order."""
        return list(self._tools.values())

    def consequential(self) -> list[Tool[object, object]]:
        """Only the tools that perform consequential actions (must be gated)."""
        return [t for t in self._tools.values() if t.consequential]

    def __iter__(self) -> Iterator[Tool[object, object]]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)
