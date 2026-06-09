# Build context = repo root
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29"

COPY services/dashboard/dashboard /app/dashboard

EXPOSE 8080
CMD ["uvicorn", "dashboard.main:app", "--host", "0.0.0.0", "--port", "8080"]
