"""Router auto-discovery — FROZEN CONTRACT.

Wave 2/3 sessions add a group-agent by dropping a package under
``app.agents.enterprise.<group>`` or ``app.agents.financial_services.<group>``
that exposes a module-level ``router: APIRouter`` in its ``router`` submodule (or
package ``__init__``). They never hand-edit a shared registry — this scanner
finds their router automatically, so parallel sessions never collide on one file.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from fastapi import APIRouter

# Packages scanned for group-agent routers, in registration order.
AGENT_PACKAGES: tuple[str, ...] = (
    "app.agents.enterprise",
    "app.agents.financial_services",
)


def _iter_router_modules(package: ModuleType) -> list[ModuleType]:
    modules: list[ModuleType] = []
    for info in pkgutil.iter_modules(package.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        group_pkg = importlib.import_module(f"{package.__name__}.{info.name}")
        # Prefer an explicit `router` submodule; fall back to the package itself.
        try:
            module = importlib.import_module(f"{package.__name__}.{info.name}.router")
        except ModuleNotFoundError:
            module = group_pkg
        modules.append(module)
    return modules


def discover_routers(package_names: tuple[str, ...] = AGENT_PACKAGES) -> list[APIRouter]:
    """Import agent packages and collect each one's ``router`` APIRouter."""
    routers: list[APIRouter] = []
    for name in package_names:
        try:
            package = importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        if not hasattr(package, "__path__"):
            continue
        for module in _iter_router_modules(package):
            router = getattr(module, "router", None)
            if isinstance(router, APIRouter):
                routers.append(router)
    return routers
