# Build context = repo root:  docker build -f services/clip-api/Dockerfile -t orwell-clip-api:dev .
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# instala a lib compartilhada (orwell_shared) + deps do serviço
COPY shared/ /src/shared/
COPY pyproject.toml /src/
RUN pip install --no-cache-dir "/src[clip-api]"

# código do serviço (pacote clip_api)
COPY services/clip-api/clip_api /app/clip_api

EXPOSE 8080
CMD ["uvicorn", "clip_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
