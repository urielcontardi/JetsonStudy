#!/usr/bin/env bash
# 80-services.sh — instala o serviço systemd que sobe o docker-compose no boot. Idempotente.
# Resultado: "os dockers sobem sozinhos" após reiniciar a placa.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_root

REPO_ROOT="$(dirname "${DEPLOY_DIR}")"
UNIT=/etc/systemd/system/orwell.service

# Descobre o binário do compose (plugin "docker compose" ou legado "docker-compose").
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif has docker-compose; then
  COMPOSE="docker-compose"
else
  err "docker compose não encontrado. Rode 40-docker.sh antes."
  exit 1
fi

log "Instalando unit systemd em ${UNIT} (WorkingDirectory=${REPO_ROOT})..."
cat >"${UNIT}" <<UNITEOF
[Unit]
Description=Orwell edge services (docker compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${REPO_ROOT}
# --profile jetson inclui o recorder (câmeras). Imagens devem ter sido buildadas antes
# (DEPLOY.md). Em boots seguintes, 'up -d' apenas inicia os containers já existentes.
ExecStart=${COMPOSE} --profile jetson up -d
ExecStop=${COMPOSE} --profile jetson down

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable orwell.service
ok "orwell.service habilitado (sobe no boot). Inicie agora com: sudo systemctl start orwell"
