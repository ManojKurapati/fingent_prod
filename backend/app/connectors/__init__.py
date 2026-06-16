"""Tool / connector layer — FROZEN CONTRACT."""

from app.connectors.base import Tool, ToolNotFoundError, ToolRegistry
from app.connectors.fake import FakeStore, build_fake_connector

__all__ = [
    "FakeStore",
    "Tool",
    "ToolNotFoundError",
    "ToolRegistry",
    "build_fake_connector",
]
