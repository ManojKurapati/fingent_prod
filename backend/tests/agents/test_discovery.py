"""Tests for router auto-discovery (the parallel-safe registration mechanism)."""

from app.agents.discovery import discover_routers
from fastapi import APIRouter

FIXTURES = ("tests.fixtures_agents",)


def _paths(routers: list[APIRouter]) -> set[str]:
    paths: set[str] = set()
    for r in routers:
        for route in r.routes:
            paths.add(route.path)  # type: ignore[attr-defined]
    return paths


def test_discovers_router_submodule_and_package_fallback() -> None:
    routers = discover_routers(FIXTURES)
    paths = _paths(routers)
    assert "/agents/alpha/ping" in paths  # via alpha/router.py
    assert "/agents/beta/ping" in paths  # via beta/__init__.py fallback


def test_skips_underscore_packages_and_loose_modules() -> None:
    routers = discover_routers(FIXTURES)
    paths = _paths(routers)
    # _hidden is underscore-prefixed -> skipped; loose.py is not a package -> skipped
    assert all("hidden" not in p for p in paths)


def test_unknown_package_is_ignored() -> None:
    assert discover_routers(("app.agents.does_not_exist",)) == []
