# syntax=docker/dockerfile:1

# Multi-stage build for a lean production image
# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

# Install uv for fast, reproducible dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (frozen = exact versions from lockfile)
# --no-dev = skip test/dev dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY src/ src/
COPY login_setup.py ./

# Install the project itself
RUN uv sync --frozen --no-dev

# Stage 2: Production image
FROM python:3.12-slim AS production

WORKDIR /app

# Copy the entire virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Add venv to PATH so we can run the installed script directly
ENV PATH="/app/.venv/bin:$PATH"

# Railway injects PORT env var (default 8000)
ENV PORT=8000

# Health check: the server responds on the MCP endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/.well-known/oauth-authorization-server')" || exit 1

EXPOSE 8000

# Run the MCP server in streamable-http mode
# Railway sets PORT env var; --port defaults to $PORT
CMD ["monarch-mcp-server", "--transport", "streamable-http"]
