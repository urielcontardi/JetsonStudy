# syntax=docker/dockerfile:1.7

# Recorder — roda NO JETSON. Base = imagem DeepStream/L4T da NVIDIA (traz GStreamer + plugins NV).
# Build context = repo root, NO PRÓPRIO JETSON (arm64/L4T):
#   docker build -f services/recorder/Dockerfile -t orwell-recorder:dev .
#
# Ajuste a tag para casar com seu JetPack (ver docs/hardware.md). Ex. JetPack 6.x -> DeepStream 7.x.
ARG DEEPSTREAM_IMAGE=nvcr.io/nvidia/deepstream:7.1-samples-multiarch
FROM ${DEEPSTREAM_IMAGE}

# Mantém downloads e índices entre rebuilds no mesmo builder. Os timeouts evitam que um mirror
# NVIDIA indisponível bloqueie por minutos a instalação de pacotes vindos dos repositórios Ubuntu.
RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && printf 'Binary::apt::APT::Keep-Downloaded-Packages "true";\n' \
      > /etc/apt/apt.conf.d/keep-cache

# Esta camada muda apenas quando a imagem base ou a lista de dependências de sistema mudar.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get -o Acquire::Retries=1 \
      -o Acquire::http::Timeout=15 \
      -o Acquire::https::Timeout=15 \
      update \
    && apt-get -o Acquire::Retries=1 \
      -o Acquire::http::Timeout=15 \
      -o Acquire::https::Timeout=15 \
      install -y --no-install-recommends \
    ffmpeg python3-pip python3-gi gir1.2-gstreamer-1.0 \
    && ffmpeg -version \
    && ffprobe -version

WORKDIR /app

# Instala a lib compartilhada (sem extras: recorder não usa fastapi/boto3).
# --no-deps evita reinstalar libs já presentes na base; pydantic/pyyaml entram explicitamente.
COPY shared/orwell_shared /app/orwell_shared
RUN pip3 install --no-cache-dir "pydantic>=2.6" "pyyaml>=6.0"

COPY services/recorder/recorder /app/recorder
COPY config /app/config

CMD ["python3", "-m", "recorder.main"]
