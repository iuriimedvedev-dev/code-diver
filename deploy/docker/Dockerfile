# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies (build essentials, git, ripgrep)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ripgrep \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project manifests and install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra mcp

# Copy repository source code
COPY . .

# Expose MCP stdio or SSE/HTTP gateway port
EXPOSE 8080

ENTRYPOINT ["uv", "run", "code-diver"]
CMD ["mcp"]
