FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD python -m src.orchestrator.healthcheck

CMD ["python", "-m", "src.orchestrator.scheduler_service"]
