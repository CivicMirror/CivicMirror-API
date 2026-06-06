# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install wheels for all production deps into /install prefix
COPY requirements/base.txt requirements/prod.txt ./
RUN pip install --no-cache-dir --prefix=/install -r prod.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Configure Playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install system dependencies for Playwright Chromium, then clean up
RUN apt-get update && \
    /usr/local/bin/playwright install-deps chromium && \
    /usr/local/bin/playwright install chromium && \
    chmod -R o+rx /ms-playwright && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy application source
COPY . .

# Collect static files (SECRET_KEY dummy is safe — only used at import time)
RUN SECRET_KEY=build-only \
    DJANGO_SETTINGS_MODULE=config.settings.base \
    python manage.py collectstatic --noinput

# Run as non-root
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser /app
USER appuser

# Prevent Python from buffering stdout/stderr so logs appear in Cloud Logging immediately
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api"]
