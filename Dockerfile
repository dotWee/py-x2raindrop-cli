# syntax=docker/dockerfile:1.7

# =============================================================================
# Stage 1: Builder - install app into a uv-managed venv
# =============================================================================
FROM python:3.12-slim AS builder

# Install uv from the official distroless image (pinned version)
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

# Container build defaults recommended for uv in Docker
ENV UV_NO_DEV=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies first for better layer caching
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-editable

# Copy source and install project non-editable into the venv
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# =============================================================================
# Stage 2: Runtime - minimal image with only project environment
# =============================================================================
FROM python:3.12-slim AS runtime

# Labels for container registry
LABEL org.opencontainers.image.title="x2raindrop-cli"
LABEL org.opencontainers.image.description="CLI tool to sync X (Twitter) Bookmarks to Raindrop.io"
LABEL org.opencontainers.image.source="https://github.com/dotWee/py-x2raindrop-cli"
LABEL org.opencontainers.image.licenses="WTFPL"

# Create non-root user for security
RUN groupadd --gid 1000 x2raindrop \
    && useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home x2raindrop

# Copy only the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Create data directory and set ownership
RUN mkdir -p /data && chown x2raindrop:x2raindrop /data

# Use the venv executables directly
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER x2raindrop

# Set working directory where config and state will be stored
WORKDIR /data

# The CLI reads config.toml and .x2raindrop/ from the current working directory.
# Mount your local directory to /data to persist configuration and state:
#   docker run -v "$PWD":/data ghcr.io/dotwee/x2raindrop-cli sync --collection 12345

ENTRYPOINT ["x2raindrop"]
CMD ["--help"]
