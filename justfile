# MUP Studio developer tasks

# list available recipes
default:
    @just --list

# install python and node dependencies
install:
    uv sync
    pnpm --dir frontend install

# run backend and frontend dev servers together
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT
    uv run uvicorn mupstudio.server.app:create_app --factory --reload --port 8000 &
    pnpm --dir frontend dev &
    wait

# backend only, with autoreload
dev-api:
    uv run uvicorn mupstudio.server.app:create_app --factory --reload --port 8000

# all fast tests
test:
    uv run pytest -q
    pnpm --dir frontend test --run

# python tests only
test-py:
    uv run pytest -q

# frontend tests only
test-js:
    pnpm --dir frontend test --run

# lint and type-check everything
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy src
    pnpm --dir frontend lint
    pnpm --dir frontend typecheck

# autofix what can be autofixed
fmt:
    uv run ruff check --fix .
    uv run ruff format .
    pnpm --dir frontend format

# build the wheel (builds the frontend first)
wheel:
    rm -rf dist
    uv build
    @ls -la dist

# install the built wheel into a throwaway venv and smoke-test it
smoke: wheel
    #!/usr/bin/env bash
    set -euo pipefail
    tmp=$(mktemp -d)
    uv venv "$tmp/venv"
    VIRTUAL_ENV="$tmp/venv" uv pip install dist/*.whl
    "$tmp/venv/bin/mupstudio" version
    "$tmp/venv/bin/mupstudio" doctor || true
    "$tmp/venv/bin/mupstudio" serve --check
    rm -rf "$tmp"

# viewport performance harness (the 120fps gate)
perf:
    pnpm --dir frontend perf
