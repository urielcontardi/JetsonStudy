# syntax=docker/dockerfile:1.7

# Recorder — roda NO JETSON. Base = imagem DeepStream/L4T da NVIDIA (traz GStreamer + plugins NV).
# Build context = repo root, NO PRÓPRIO JETSON (arm64/L4T):
#   docker build -f services/recorder/Dockerfile -t orwell-recorder:dev .
#
# Ajuste a tag para casar com seu JetPack (ver docs/hardware.md). Ex. JetPack 6.x -> DeepStream 7.x.
ARG DEEPSTREAM_IMAGE=nvcr.io/nvidia/deepstream:7.1-samples-multiarch
FROM ${DEEPSTREAM_IMAGE}

# Loop de retry cobre hash-mismatch transitório de CDN e mirrors NVIDIA indisponíveis.
#
# IMPORTANTE (regressão real, 2026-06-09): a versão anterior ENGOLIA a falha.
# O `ffmpeg -version` só controlava o `break`; se o apt registrava o pacote como
# instalado mas a extração falhava (hiccup de rede / cache-mount não commitada),
# as tentativas seguintes viam o pacote "já instalado" e não reinstalavam, e o
# `&& rm -rf` final retornava 0 → a imagem subia com ffmpeg QUEBRADO
# (libavcodec.so.58 ausente). Resultado: probe_media falhava em todo fragmento,
# publish_event_clip lançava NoSegments e NENHUM clipe periódico era enviado.
#
# Correções:
#   - `update || true`: o repo l4t-repo.nvidia.com às vezes não resolve DNS e não
#     é necessário para o ffmpeg (que vem de ports.ubuntu.com). Não pode abortar.
#   - gi/GStreamer SEM --reinstall: já vêm da base DeepStream; reinstalá-los forçaria
#     buscar `libgirepository-...-with-libffi8` no l4t-repo (que pode estar sem DNS).
#     Instalar sem --reinstall é no-op quando já satisfeito e não toca o l4t-repo.
#   - ⚠️ `--reinstall` nas LIBS libav* explicitamente, não só no ffmpeg: a base
#     DeepStream traz libavcodec58 & cia. com dpkg `ii` mas SEM os arquivos .so
#     (NVIDIA enxuga a imagem). Como `apt install ffmpeg` vê a dependência
#     "satisfeita", ela NÃO é reextraída e o ffmpeg sobe sem libavcodec.so.58.
#     Foi exatamente esse o defeito que parou o envio periódico em 2026-06-09.
#     `--reinstall` força a re-extração e os .so voltam.
#   - `ldd ... not found`: valida que as .so REALMENTE existem, não só que o binário roda.
#   - `exit 1` no fim: o build FALHA ALTO se o ffmpeg ficar inutilizável.
RUN set -eu; \
    ok=0; \
    for attempt in 1 2 3 4 5; do \
      rm -rf /var/lib/apt/lists/*; \
      apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 update || true; \
      apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 \
        install -y --no-install-recommends \
        python3-pip python3-gi gir1.2-gstreamer-1.0 || true; \
      if apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 \
           install -y --reinstall --no-install-recommends \
           ffmpeg \
           libavcodec58 libavdevice58 libavfilter7 libavformat58 libavutil56 \
           libpostproc55 libswresample3 libswscale5 \
           libvpx7 libmp3lame0 libx264-163 libx265-199 libxvidcore4 \
           libmpg123-0 libflac8 \
         && ffmpeg -version >/dev/null \
         && ffprobe -version >/dev/null \
         && ! ldd "$(command -v ffprobe)" | grep -q 'not found'; then \
        ok=1; break; \
      fi; \
      echo "recorder build: tentativa $attempt falhou (ffmpeg inutilizável), repetindo..."; \
      sleep 5; \
    done; \
    [ "$ok" = 1 ] || { echo "FATAL: ffmpeg/ffprobe inutilizável após as tentativas"; exit 1; }; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala a lib compartilhada (sem extras: recorder não usa fastapi/boto3).
# --no-deps evita reinstalar libs já presentes na base; pydantic/pyyaml entram explicitamente.
COPY shared/orwell_shared /app/orwell_shared
RUN pip3 install --no-cache-dir "pydantic>=2.6" "pyyaml>=6.0"

COPY services/recorder/recorder /app/recorder
COPY config /app/config

CMD ["python3", "-m", "recorder.main"]
