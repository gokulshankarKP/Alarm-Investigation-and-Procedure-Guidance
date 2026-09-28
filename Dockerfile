# One image for every Python service; docker-compose.yml selects the command per service.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app:/app/apps/alarm-api-simulator:/app/apps/backend:/app/apps/frontend:/app/mcp-servers/alarm-management

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY shared/ shared/
COPY connectors/ connectors/
COPY rag/ rag/
COPY apps/ apps/
COPY mcp-servers/ mcp-servers/
COPY pyproject.toml README.md ./

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8000 9000 8080 8501
CMD ["python", "-m", "copilot", "--host", "0.0.0.0", "--port", "8080"]
