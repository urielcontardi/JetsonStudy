#!/usr/bin/env bash
# host-verify.sh — checagens de sanidade pós-provisionamento. Não altera nada.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

fail=0
check() { # check "descrição" "comando..."
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "${desc}"; else err "${desc}"; fail=1; fi
}

log "===== Verificação do host Orwell ====="

# Plataforma
if [ -f /etc/nv_tegra_release ]; then ok "JetPack/L4T presente"; else err "JetPack/L4T ausente"; fail=1; fi

# Base
check "ffmpeg instalado" has ffmpeg
check "python3 instalado" has python3

# Storage
if [ -d "${DATA_DIR:-/nonexistent}" ]; then
  ok "DATA_DIR existe (${DATA_DIR}) — livre: $(df -h --output=avail "${DATA_DIR}" | tail -1 | tr -d ' ')"
else
  err "DATA_DIR ausente (${DATA_DIR:-<não definido>})"; fail=1
fi

# Docker + runtime nvidia
check "Docker ativo" systemctl is-active --quiet docker
if docker info 2>/dev/null | grep -qi nvidia; then ok "Runtime nvidia no Docker"; else err "Runtime nvidia ausente"; fail=1; fi

# Câmeras (após driver GMSL + reboot)
if ls /dev/video* >/dev/null 2>&1; then
  ok "Dispositivos de vídeo: $(ls /dev/video* | tr '\n' ' ')"
else
  warn "Nenhum /dev/video* — driver GMSL instalado e rebootado? Câmeras conectadas?"
fi

# Tailscale (autenticação é passo pós-bootstrap; warning se não conectado)
if has tailscale && tailscale status >/dev/null 2>&1; then
  ok "Tailscale conectado (IP: $(tailscale ip -4 2>/dev/null | head -1))"
elif has tailscale; then
  warn "Tailscale instalado mas não autenticado — rode: sudo tailscale up --hostname ${DEVICE_NAME:-orwell} --ssh"
else
  err "Tailscale não instalado"; fail=1
fi

# Tempo
if timedatectl show -p NTPSynchronized 2>/dev/null | grep -q "yes"; then
  ok "Relógio sincronizado (NTP)"
else
  warn "NTP ainda não sincronizado (pode levar alguns segundos)"
fi

echo
# ---------------------------------------------------------------------------
# Relatório de versões (para auditoria e rastreabilidade de frota)
# ---------------------------------------------------------------------------
log "===== Relatório de versões ====="

_ver_l4t()      { grep -oP 'REVISION: \K[^,]+' /etc/nv_tegra_release 2>/dev/null || echo "n/a"; }
_ver_kernel()   { uname -r 2>/dev/null || echo "n/a"; }
_ver_docker()   { docker --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1 || echo "n/a"; }
_ver_nvrt()     { dpkg -l nvidia-container-toolkit 2>/dev/null | awk '/^ii/{print $3}' || echo "n/a"; }
_ver_cuda()     { nvcc --version 2>/dev/null | grep -oP 'release \K[\d.]+' || dpkg -l cuda-toolkit-\* 2>/dev/null | awk '/^ii/{print $3}' | head -1 || echo "n/a"; }
_ver_gst()      { gst-inspect-1.0 --version 2>/dev/null | grep -oP '[\d.]+' | head -1 || echo "n/a"; }
_ver_gmsl()     { dpkg -l 'stereolabs-*' 2>/dev/null | awk '/^ii/{print $2"="$3}' | tr '\n' ' ' || echo "n/a"; }
_ver_python()   { python3 --version 2>/dev/null | awk '{print $2}' || echo "n/a"; }
_ver_ffmpeg()   { ffmpeg -version 2>/dev/null | grep -oP 'ffmpeg version \K\S+' || echo "n/a"; }
_ver_ts()       { tailscale version 2>/dev/null | head -1 || echo "n/a"; }
_held_l4t()     { dpkg -l 'nvidia-l4t-*' 2>/dev/null | awk '/^hi/{print $2}' | wc -l | tr -d ' '; }

REPORT_FILE="/var/lib/orwell/versions-report.env"
mkdir -p /var/lib/orwell 2>/dev/null || true

{
  echo "# Orwell host versions — $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "DEVICE_NAME=${DEVICE_NAME:-<não definido>}"
  echo "L4T_REVISION=$(_ver_l4t)"
  echo "KERNEL=$(_ver_kernel)"
  echo "DOCKER=$(_ver_docker)"
  echo "NVIDIA_CONTAINER_TOOLKIT=$(_ver_nvrt)"
  echo "CUDA=$(_ver_cuda)"
  echo "GSTREAMER=$(_ver_gst)"
  echo "GMSL_DRIVER=$(_ver_gmsl)"
  echo "PYTHON3=$(_ver_python)"
  echo "FFMPEG=$(_ver_ffmpeg)"
  echo "TAILSCALE=$(_ver_ts)"
  echo "NVIDIA_L4T_HELD_COUNT=$(_held_l4t)"
} | tee "${REPORT_FILE}"

ok "Relatório salvo em ${REPORT_FILE}"

echo
if [ "$fail" -eq 0 ]; then ok "Host OK para deploy."; else err "Há itens pendentes acima."; fi
exit "$fail"
