# The search API (search-api/src/api), for Cloud Run, and the jobs under
# routines/ (insights-sync, messaging-sync), which run it with --command.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock README.md ./
COPY infrastructure ./infrastructure
COPY routines ./routines
COPY search-api/src ./search-api/src
RUN uv sync --frozen --no-dev

# Cloud Run sets PORT.
CMD exec uvicorn api.app:create_app --factory --host 0.0.0.0 --port "${PORT:-8080}"
