# syntax=docker/dockerfile:1
# AI-Native Finance Platform — backend (FastAPI + agent runtime)
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# uv is the package manager (see pyproject.toml + uv.lock).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 1) Install third-party deps first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 2) Copy the application and install the project itself.
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

EXPOSE 8000

# Put the venv on PATH so `uvicorn`/`python` resolve directly.
ENV PATH="/app/.venv/bin:${PATH}"

# Default = product app (in-memory fakes + stub Claude transport; boots with no
# API key). For the seeded Playwright demo server use: app.e2e_server:app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
