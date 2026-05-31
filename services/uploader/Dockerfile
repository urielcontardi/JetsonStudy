# Build context = repo root:  docker build -f services/uploader/Dockerfile -t orwell-uploader:dev .
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY shared/ /src/shared/
COPY pyproject.toml /src/
RUN pip install --no-cache-dir "/src[uploader]"

COPY services/uploader/uploader /app/uploader
COPY config /app/config

CMD ["python", "-m", "uploader.main"]
