FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 1000 app
COPY pyproject.toml ./
COPY screening_agent ./screening_agent
RUN pip install .
USER app
EXPOSE 8000
CMD ["uvicorn", "screening_agent.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
