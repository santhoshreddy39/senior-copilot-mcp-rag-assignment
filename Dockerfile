# Single image shared by all three Python services (alarm-api, copilot-backend,
# frontend) — docker-compose.yml selects the process via `command:`. This keeps the
# build fast and avoids duplicating the dependency layer three times; the services
# are still fully independent processes / containers at runtime.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-llm.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Optional LLM provider SDKs — build with `--build-arg INSTALL_LLM_SDKS=true` to
# include them; omitted by default so the base image stays lean for the fully
# offline (TemplateProvider) grading path.
ARG INSTALL_LLM_SDKS=false
RUN if [ "$INSTALL_LLM_SDKS" = "true" ]; then pip install --no-cache-dir -r requirements-llm.txt; fi

COPY . .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8000 8100 8501
