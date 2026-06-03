# Recorder — roda NO JETSON. Base = imagem DeepStream/L4T da NVIDIA (traz GStreamer + plugins NV).
# Build context = repo root, NO PRÓPRIO JETSON (arm64/L4T):
#   docker build -f services/recorder/Dockerfile -t orwell-recorder:dev .
#
# Ajuste a tag para casar com seu JetPack (ver docs/hardware.md). Ex. JetPack 6.x -> DeepStream 7.x.
ARG DEEPSTREAM_IMAGE=nvcr.io/nvidia/deepstream:7.1-samples-multiarch
FROM ${DEEPSTREAM_IMAGE}

# python3-gi (gi.repository.Gst) costuma já existir na base L4T; garantimos mesmo assim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip python3-gi gir1.2-gstreamer-1.0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala a lib compartilhada (sem extras: recorder não usa fastapi/boto3).
# --no-deps evita reinstalar libs já presentes na base; pydantic/pyyaml entram explicitamente.
COPY shared/ /src/shared/
COPY pyproject.toml /src/
RUN pip3 install --no-cache-dir /src

COPY services/recorder/recorder /app/recorder
COPY config /app/config

CMD ["python3", "-m", "recorder.main"]
