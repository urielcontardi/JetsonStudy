#!/usr/bin/env bash
# 50-nvidia-runtime.sh — garante o NVIDIA Container Runtime no Docker. Idempotente.
# No JetPack, o runtime normalmente já vem instalado; aqui garantimos e (opcional)
# tornamos 'nvidia' o runtime padrão (recomendado p/ GPU + câmera nos containers).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_root

if ! has nvidia-container-runtime && ! dpkg -l 2>/dev/null | grep -q nvidia-container-toolkit; then
  log "Instalando nvidia-container-toolkit..."
  apt-get update -y
  apt-get install -y nvidia-container-toolkit || \
    warn "Falha ao instalar via apt. No JetPack o runtime costuma já existir; verifique 'docker info | grep -i runtime'."
fi

DAEMON_JSON="/etc/docker/daemon.json"
if [ "${DOCKER_DEFAULT_RUNTIME_NVIDIA:-true}" = "true" ]; then
  log "Configurando 'nvidia' como default-runtime do Docker em ${DAEMON_JSON}..."
  mkdir -p /etc/docker
  if [ ! -f "$DAEMON_JSON" ]; then
    cat >"$DAEMON_JSON" <<'JSON'
{
  "runtimes": {
    "nvidia": {
      "path": "nvidia-container-runtime",
      "runtimeArgs": []
    }
  },
  "default-runtime": "nvidia"
}
JSON
    systemctl restart docker
    ok "daemon.json criado e Docker reiniciado."
  else
    if has jq; then
      tmp=$(mktemp)
      jq '.runtimes.nvidia = {"path":"nvidia-container-runtime","runtimeArgs":[]} | ."default-runtime" = "nvidia"' \
        "$DAEMON_JSON" >"$tmp" && mv "$tmp" "$DAEMON_JSON"
      systemctl restart docker
      ok "daemon.json atualizado e Docker reiniciado."
    else
      warn "jq ausente; edite ${DAEMON_JSON} manualmente para default-runtime=nvidia."
    fi
  fi
fi

log "Validando acesso à GPU em container (best-effort)..."
if docker info 2>/dev/null | grep -qi nvidia; then
  ok "Runtime nvidia presente no Docker."
else
  warn "Runtime nvidia não detectado em 'docker info'. Revise no JetPack."
fi
