#!/usr/bin/env bash
# 10-base.sh — pacotes-base e utilitários do host. Idempotente.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_root

log "Atualizando índices apt e pacotes base..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y

# JetPack/L4T é gerenciado pela NVIDIA via SDK Manager, não via apt upgrade.
# Os post-install scripts de nvidia-l4t-kernel/bootloader regravem o bootloader
# e falham em placas com DTB customizado (ex.: ZED Box da Stereolabs).
# Colocamos todos em hold antes de qualquer upgrade para evitar essa quebra.
held=$(dpkg -l 'nvidia-l4t-*' 2>/dev/null | awk '/^[hi]i/{print $2}' | tr '\n' ' ')
if [ -n "${held}" ]; then
  # shellcheck disable=SC2086
  apt-mark hold ${held}
  log "nvidia-l4t-* em hold: ${held}"
fi

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
