#!/usr/bin/env bash
# 99-bootstrap.sh — provisiona uma placa zerada (JetPack/L4T já flashado) do zero.
# Roda os passos em ordem, de forma idempotente. Pode ser re-executado com segurança.
#
#   Uso:  sudo ./deploy/99-bootstrap.sh
#
# Pré-requisito: JetPack/L4T já instalado (ver deploy/README.md, passo 0).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_root

log "================ Orwell — bootstrap de host ================"
log "Device: ${DEVICE_NAME:-<não definido>} | Data dir: ${DATA_DIR:-<não definido>}"

mkdir -p /var/lib/orwell 2>/dev/null || true

STEPS=(
  "10-base.sh"
  "20-storage.sh"
  "40-docker.sh"
  "50-nvidia-runtime.sh"
  "60-tailscale.sh"
  "70-time-ntp.sh"
  "30-gmsl-driver.sh"   # por último: exige reboot
)

for s in "${STEPS[@]}"; do
  log "---- Executando ${s} ----"
  bash "${DEPLOY_DIR}/${s}"
done

echo
if [ -f /var/lib/orwell/.gmsl-needs-reboot ]; then
  warn "=============================================================="
  warn " Provisionamento base concluído, MAS o driver GMSL exige REBOOT."
  warn " 1) sudo reboot"
  warn " 2) após reiniciar, valide:  sudo ./deploy/host-verify.sh"
  warn " 3) suba os serviços:        docker compose up -d --build"
  warn "=============================================================="
  rm -f /var/lib/orwell/.gmsl-needs-reboot
else
  ok "Provisionamento concluído. Valide com:  sudo ./deploy/host-verify.sh"
fi
