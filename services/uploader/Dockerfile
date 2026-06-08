# Build context = repo root
FROM python:3.10-slim

WORKDIR /app

COPY shared/ /src/shared/
COPY pyproject.toml /src/
RUN pip install --no-cache-dir "/src"

COPY services/uploader/uploader /app/uploader

CMD ["python", "-m", "uploader.main"]
