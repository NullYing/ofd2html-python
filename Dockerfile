FROM python:3.12-slim

# lxml runtime shared libs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Reproducible install from the lockfile, into the system environment.
ENV UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uvicorn", "ofd2html.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
