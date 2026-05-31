#!/usr/bin/env bash
# 10-base.sh — pacotes-base e utilitários do host. Idempotente.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_root

log "Atualizando índices apt e pacotes base..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y

# Atualização do sistema (pode ser pesada na 1ª vez). Comente se preferir
# controlar upgrades manualmente.
apt-get upgrade -y

log "Instalando utilitários base..."
apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  gnupg \
  git \
  jq \
  htop \
  nvme-cli \
  ffmpeg \
  python3 \
  python3-venv \
  python3-pip

ok "Base pronta."
