
# =========================
# 1. Base Builder
# =========================
FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_HTTP_TIMEOUT=30000

# Build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install pinned uv
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /uvx /bin/

WORKDIR /app

# Copy dependency files
COPY backend/pyproject.toml backend/uv.lock ./


# =========================
# 2. Development Builder
# =========================
FROM base AS development-builder

# Install production + development dependencies
RUN uv sync --frozen --no-install-project


# =========================
# 3. Production Builder
# =========================
FROM base AS production-builder

# Install production dependencies only
RUN uv sync --frozen --no-dev --no-install-project


# =========================
# 4. Development Runtime
# =========================
FROM python:3.12-slim-bookworm AS development

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install runtime libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libffi8 \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

# Create application user matching Fedora UID/GID
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

# Copy virtual environment
COPY --from=development-builder --chown=appuser:appuser \
    /app/.venv /opt/venv

# Copy Django project
COPY --chown=appuser:appuser backend/ /app/

USER appuser

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


# =========================
# 5. Production Runtime
# =========================
FROM python:3.12-slim-bookworm AS production

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Create non-root application user
RUN groupadd --system appuser && \
    useradd --system --gid appuser --create-home appuser

WORKDIR /app

# Install runtime libraries only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libffi8 \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

# Copy production virtual environment
COPY --from=production-builder --chown=appuser:appuser \
    /app/.venv /opt/venv

# Copy Django project
COPY --chown=appuser:appuser backend/ /app/

USER appuser

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
