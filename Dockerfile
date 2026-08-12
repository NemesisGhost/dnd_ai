# Production-oriented image for the D&D AI World Platform.
#
# One image, multiple entrypoints (docs/DEVELOPMENT.md §2, PLAN.md §31.3):
# migrations/seeds today, the API/worker/adapter processes once
# src/dnd_ai/api exists. It is not a fake API image — src/dnd_ai/api has no
# committed source yet, so the only real runnable role today is the
# database toolchain (Alembic). The default command applies migrations to
# whatever DATABASE_URL points at.
#
# Built and run via compose.yaml — see docs/DEVELOPMENT.md §3 for the
# self-hosted workflow.

FROM python:3.12-slim-bookworm AS base

# Pinned uv release matching this repo's toolchain (docs/DEVELOPMENT.md §1).
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Dependencies first, separately from application code, so an app-only
# change doesn't invalidate the (slow) dependency-resolution layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY src ./src
COPY database ./database

RUN uv sync --locked --no-dev

RUN useradd --create-home --uid 1000 dndai \
    && chown -R dndai:dndai /app
USER dndai

ENTRYPOINT ["uv", "run", "--no-sync"]
CMD ["alembic", "-c", "database/alembic.ini", "upgrade", "head"]
