# syntax=docker/dockerfile:1.7

# Recorder — roda NO JETSON. Base = imagem DeepStream/L4T da NVIDIA (traz GStreamer + plugins NV).
# Build context = repo root, NO PRÓPRIO JETSON (arm64/L4T):
#   docker build -f services/recorder/Dockerfile -t orwell-recorder:dev .
#
# Ajuste a tag para casar com seu JetPack (ver docs/hardware.md). Ex. JetPack 6.x -> DeepStream 7.x.
ARG DEEPSTREAM_IMAGE=nvcr.io/nvidia/deepstream:7.1-samples-multiarch
FROM ${DEEPSTREAM_IMAGE}

# Loop de retry cobre hash-mismatch transitório de CDN e mirrors NVIDIA indisponíveis.
# Limpa /var/lib/apt/lists antes de cada tentativa para forçar re-download do índice.
RUN for attempt in 1 2 3; do \
      apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 update \
      && apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 \
         install -y --no-install-recommends \
         ffmpeg python3-pip python3-gi gir1.2-gstreamer-1.0 \
      && ffmpeg -version && ffprobe -version \
      && break; \
      echo "apt attempt $attempt failed, retrying..."; \
      rm -rf /var/lib/apt/lists/*; \
      sleep 5; \
    done \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala a lib compartilhada (sem extras: recorder não usa fastapi/boto3).
# --no-deps evita reinstalar libs já presentes na base; pydantic/pyyaml entram explicitamente.
COPY shared/orwell_shared /app/orwell_shared
RUN pip3 install --no-cache-dir "pydantic>=2.6" "pyyaml>=6.0"

COPY services/recorder/recorder /app/recorder
COPY config /app/config

CMD ["python3", "-m", "recorder.main"]
