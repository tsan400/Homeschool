FROM python:3.12-slim

# Fonts for the packets (Typst falls back to its built-ins if these are missing).
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY config config
COPY content content
COPY src src
RUN uv sync --frozen --no-dev

# All data (database + encrypted files) lives on the mounted volume.
ENV HS_HOME=/data PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["hs", "serve", "--host", "0.0.0.0", "--port", "8000"]
