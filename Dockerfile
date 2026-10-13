FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.19

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend ./backend
COPY docs ./docs
COPY README.md ./

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=2).read()"

# One worker process with threads: on a 512 MB free instance a second process
# would double memory use, and with RUN_WORKERS_IN_PROCESS=true the import and
# enrichment threads run inside this same process.
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:$PORT --worker-class gthread --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-4} --timeout ${GUNICORN_TIMEOUT:-120} --access-logfile - backend.app:app"]
