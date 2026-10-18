# =============================================================================
# STAGE 1: Builder
# =============================================================================
FROM python:3.13-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install compilation prerequisites
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install project dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .[r2]

# =============================================================================
# STAGE 2: Runtime Image
# =============================================================================
FROM python:3.13-slim-bookworm AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENVIRONMENT=production

WORKDIR /app

# Install minimal runtime shared libraries and curl for health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged service user and group (least-privilege security)
RUN groupadd -g 10001 -r appgroup && \
    useradd -u 10001 -r -g appgroup -s /sbin/nologin -d /app appuser

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application code, Alembic migrations, and configuration
COPY alembic.ini ./
COPY alembic ./alembic
COPY backend ./backend

# Create storage mount directory and set file permissions
RUN mkdir -p /app/var/storage && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Dependency-free liveness probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/livez || exit 1

# Production ASGI server entry point
CMD ["python", "-m", "backend.main"]

