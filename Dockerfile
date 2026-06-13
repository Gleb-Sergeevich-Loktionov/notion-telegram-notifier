FROM python:3.12-slim

# uv — fast, reproducible dependency installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install runtime dependencies from pyproject.toml (single source of truth).
# Package code is needed for the build backend to resolve the wheel.
COPY pyproject.toml README.md ./
COPY notify_bot/ ./notify_bot/
RUN uv pip install --system --no-cache .

# Composition root
COPY main.py ./

# Run as an unprivileged user; /data holds the SQLite database
RUN useradd --no-create-home --shell /bin/false botuser \
    && mkdir -p /data \
    && chown botuser:botuser /data

USER botuser

VOLUME ["/data"]

CMD ["python", "main.py"]
