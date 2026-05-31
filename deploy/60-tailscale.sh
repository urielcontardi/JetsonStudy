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

up_args=(--hostname "${DEVICE_NAME}")
[ "${TS_ENABLE_SSH:-true}" = "true" ] && up_args+=(--ssh)
if [ -n "${TS_AUTHKEY:-}" ]; then
  up_args+=(--authkey "${TS_AUTHKEY}")
  log "Conectando ao tailnet de forma não-interativa..."
else
  log "Sem TS_AUTHKEY: o 'tailscale up' abrirá um link de login interativo."
fi

tailscale up "${up_args[@]}"

ok "Tailscale conectado como '${DEVICE_NAME}'. IP: $(tailscale ip -4 2>/dev/null | head -1 || echo '?')"
