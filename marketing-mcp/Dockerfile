# hd-marketing-mcp, for Cloud Run. See marketing-mcp/README.md.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# generate_slide screenshots its HTML in headless Chromium.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps --only-shell chromium
COPY src ./src

# Cloud Run sets PORT; the server listens on it at /mcp.
CMD ["python", "src/mcp-server.py"]
