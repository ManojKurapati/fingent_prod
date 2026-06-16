"""Tests for the typed Tool interface, registry, and the fake connector."""

import pytest
from app.connectors import (
    FakeStore,
    Tool,
    ToolNotFoundError,
    ToolRegistry,
    build_fake_connector,
)


class _Greet(Tool[str, str]):
    name = "greet"
    consequential = False

    async def invoke(self, payload: str) -> str:
        return f"hello {payload}"


def test_tool_defaults_to_non_consequential() -> None:
    class _Plain(Tool[None, None]):
        name = "plain"

        async def invoke(self, payload: None) -> None:
            return None

    assert _Plain().consequential is False


async def test_tool_invoke_is_typed_and_awaitable() -> None:
    assert await _Greet().invoke("world") == "hello world"


def test_registry_registers_and_fetches_by_name() -> None:
    reg = ToolRegistry()
    tool = reg.register(_Greet())
    assert reg.get("greet") is tool
    assert [t.name for t in reg.all()] == ["greet"]


def test_registry_rejects_duplicate_names() -> None:
    reg = ToolRegistry()
    reg.register(_Greet())
    with pytest.raises(ValueError):
        reg.register(_Greet())


def test_registry_get_unknown_raises() -> None:
    with pytest.raises(ToolNotFoundError):
        ToolRegistry().get("nope")


def test_registry_filters_consequential_tools() -> None:
    reg = build_fake_connector()
    names = {t.name for t in reg.consequential()}
    # the fake connector's write/delete tools are consequential; read is not
    assert "kv_write" in names
    assert "kv_read" not in names
    assert all(t.consequential for t in reg.consequential())


async def test_fake_connector_read_after_write_roundtrips() -> None:
    store = FakeStore()
    reg = build_fake_connector(store=store)
    write = reg.get("kv_write")
    read = reg.get("kv_read")

    await write.invoke({"key": "k", "value": "v"})
    assert await read.invoke("k") == "v"
    # the write was a consequential action
    assert write.consequential is True


async def test_fake_connector_read_missing_returns_none() -> None:
    reg = build_fake_connector()
    assert await reg.get("kv_read").invoke("absent") is None


def test_registry_is_iterable_and_sized() -> None:
    reg = build_fake_connector()
    assert len(reg) == 3
    assert {t.name for t in reg} == {"kv_read", "kv_write", "kv_delete"}


async def test_fake_connector_delete_reports_presence() -> None:
    reg = build_fake_connector()
    await reg.get("kv_write").invoke({"key": "k", "value": "v"})
    assert await reg.get("kv_delete").invoke("k") is True
    assert await reg.get("kv_delete").invoke("k") is False
