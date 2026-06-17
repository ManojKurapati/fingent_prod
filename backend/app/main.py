"""FastAPI application factory — wires shared platform + auto-discovered agents."""

from __future__ import annotations

from fastapi import FastAPI

from app.agents.discovery import discover_routers
from app.api.context import AppContext, build_context
from app.api.platform import router as platform_router


def create_app(context: AppContext | None = None) -> FastAPI:
    """Build the FastAPI app.

    Pass a ``context`` to inject test fakes; otherwise the default in-process
    context is built. Group-agent routers are discovered automatically.
    """
    app = FastAPI(title="Fingent — AI-Native Financial Services Platform", version="0.1.0")
    app.state.context = context or build_context()

    app.include_router(platform_router)
    for router in discover_routers():
        app.include_router(router)

    return app


app = create_app()
