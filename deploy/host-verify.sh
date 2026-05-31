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

# Tailscale
if has tailscale && tailscale status >/dev/null 2>&1; then
  ok "Tailscale conectado (IP: $(tailscale ip -4 2>/dev/null | head -1))"
else
  err "Tailscale não conectado"; fail=1
fi

# Tempo
if timedatectl show -p NTPSynchronized 2>/dev/null | grep -q "yes"; then
  ok "Relógio sincronizado (NTP)"
else
  warn "NTP ainda não sincronizado (pode levar alguns segundos)"
fi

echo
if [ "$fail" -eq 0 ]; then ok "Host OK para deploy."; else err "Há itens pendentes acima."; fi
exit "$fail"
