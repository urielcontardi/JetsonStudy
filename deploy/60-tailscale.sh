#!/usr/bin/env bash
# 60-tailscale.sh — instala e conecta o Tailscale. Idempotente.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_root
require_var DEVICE_NAME

if has tailscale; then
  ok "Tailscale já instalado: $(tailscale version | head -1)"
else
  log "Instalando Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
fi

systemctl enable --now tailscaled

if [ -n "${TS_AUTHKEY:-}" ]; then
  up_args=(--hostname "${DEVICE_NAME}" --authkey "${TS_AUTHKEY}")
  [ "${TS_ENABLE_SSH:-true}" = "true" ] && up_args+=(--ssh)
  log "Conectando ao tailnet com authkey..."
  tailscale up "${up_args[@]}"
  ok "Tailscale conectado como '${DEVICE_NAME}'. IP: $(tailscale ip -4 2>/dev/null | head -1 || echo '?')"
else
  warn "TS_AUTHKEY não definida — Tailscale instalado mas NÃO conectado."
  warn "Para autenticar depois, rode:"
  warn "  sudo tailscale up --hostname ${DEVICE_NAME} --ssh"
  warn "  (ou defina TS_AUTHKEY em deploy/00-versions.env e re-rode este script)"
fi
