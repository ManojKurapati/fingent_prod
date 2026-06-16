"""Global guardrail audit utilities.

Two complementary checks make the platform-wide invariant *"no consequential
action executes without an approval record"* enforceable in CI:

* :func:`consequential_tool_classes` discovers — by importing every group-agent
  module and walking the :class:`Tool` subclass tree — every tool flagged
  ``consequential = True``. A runtime test submits each through a
  :class:`GuardrailEngine` and asserts it is held (default-deny) until approved.

* :func:`find_consequential_bypasses` statically scans agent source for any
  *direct* ``.invoke(...)`` call on a consequential tool — i.e. a call that would
  skip the guardrail. Agent code must only hand consequential tools to
  ``guardrails.submit(...)``; the engine is the sole caller of their ``invoke``.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any

from app.connectors import Tool

# Packages whose consequential tools are audited (the real business actions).
AGENT_PACKAGES: tuple[str, ...] = (
    "app.agents.enterprise",
    "app.agents.financial_services",
)


def _import_all(package_name: str) -> None:
    package = importlib.import_module(package_name)
    for info in pkgutil.walk_packages(package.__path__, prefix=f"{package.__name__}."):
        importlib.import_module(info.name)


def _all_subclasses(cls: type) -> set[type]:
    found: set[type] = set()
    for sub in cls.__subclasses__():
        found.add(sub)
        found |= _all_subclasses(sub)
    return found


def discover_tool_classes(packages: tuple[str, ...] = AGENT_PACKAGES) -> list[type[Tool[Any, Any]]]:
    """Import all agent modules and return every concrete Tool subclass they define."""
    for package in packages:
        _import_all(package)
    classes = [
        cls
        for cls in _all_subclasses(Tool)
        if cls.__module__.startswith(packages) and not inspect.isabstract(cls)
    ]
    return sorted(classes, key=lambda c: (c.__module__, c.__name__))


def consequential_tool_classes(
    packages: tuple[str, ...] = AGENT_PACKAGES,
) -> list[type[Tool[Any, Any]]]:
    """Every concrete agent tool flagged ``consequential = True``."""
    return [cls for cls in discover_tool_classes(packages) if getattr(cls, "consequential", False)]


def _agent_source_files(packages: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for package in packages:
        module = importlib.import_module(package)
        for path in module.__path__:
            files.extend(Path(path).rglob("*.py"))
    return sorted(files)


def _consequential_class_names(packages: tuple[str, ...]) -> set[str]:
    return {cls.__name__ for cls in consequential_tool_classes(packages)}


def _call_name(node: ast.expr) -> str | None:
    """The simple name a Call constructs, e.g. ``RouteOrderTool()`` -> 'RouteOrderTool'."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def _target_key(node: ast.expr) -> str | None:
    """A stable key for an assignment target (``x`` or ``self._tool``)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def scan_source_for_bypasses(
    source: str, *, filename: str, consequential_names: set[str]
) -> list[str]:
    """Scan one module's source for direct ``.invoke`` on a consequential tool."""
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []

    # variable/attribute names currently bound to a consequential tool instance
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            ctor = _call_name(node.value)
            if ctor in consequential_names:
                for target in node.targets:
                    key = _target_key(target)
                    if key is not None:
                        bound[key] = ctor

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "invoke":
            continue
        receiver = node.func.value
        # direct: RouteOrderTool().invoke(...)
        ctor = _call_name(receiver)
        if ctor in consequential_names:
            violations.append(f"{filename}:{node.lineno}: direct invoke on {ctor}()")
            continue
        # via a bound variable: self._tool.invoke(...)
        key = _target_key(receiver)
        if key is not None and key in bound:
            violations.append(
                f"{filename}:{node.lineno}: direct invoke on {bound[key]} (via {key})"
            )

    return violations


def find_consequential_bypasses(
    packages: tuple[str, ...] = AGENT_PACKAGES,
) -> list[str]:
    """Return descriptions of any direct ``.invoke`` on a consequential tool.

    An empty list means every consequential tool is only ever routed through the
    guardrail engine (no bypass). A non-empty list fails the build.
    """
    consequential_names = _consequential_class_names(packages)
    violations: list[str] = []
    for file in _agent_source_files(packages):
        violations.extend(
            scan_source_for_bypasses(
                file.read_text(),
                filename=str(file),
                consequential_names=consequential_names,
            )
        )
    return violations
