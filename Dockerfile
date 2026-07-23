FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY more_core/ more_core/
RUN pip install --no-cache-dir -e "more_core[api]"

# Runtime defaults
ENV MORE_LMSTUDIO_ENDPOINT=http://host.docker.internal:1234/v1
ENV MORE_OLLAMA_ENDPOINT=http://host.docker.internal:11434
ENV MORE_LLM_FALLBACK_CHAIN=lmstudio,ollama
ENV MORE_ENABLE_SYMBOLIC=1
ENV MORE_ENABLE_EVOLUTION=0
ENV MORE_ENABLE_METACOGNITION=0

EXPOSE 8011
CMD ["more-os", "serve", "--host", "0.0.0.0", "--port", "8011"]
