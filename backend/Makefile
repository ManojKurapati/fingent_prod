.PHONY: install test cov lint typecheck check fmt

install:
	uv sync

test:
	uv run pytest

cov:
	uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=85

lint:
	uv run ruff check app tests
	uv run ruff format --check app tests

fmt:
	uv run ruff format app tests
	uv run ruff check --fix app tests

typecheck:
	uv run mypy

check: lint typecheck cov
