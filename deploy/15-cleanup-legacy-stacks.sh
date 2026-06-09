#!/usr/bin/env bash
# 15-cleanup-legacy-stacks.sh — remove stacks Docker legados que disputam a câmera. Idempotente.
#
# Contexto: protótipos antigos (ex.: "jetsonstudy") montavam /dev/video0 e o socket do Argus
# (/tmp/argus_socket) e ficavam em crash-loop, disputando a câmera GMSL com o stack orwell e
# causando gaps no preview ("stream not found"). Este script garante que eles não voltem.
# Ver causa raiz em docs/decisions/ e CLAUDE.md (regra: nada toca o host de forma ad-hoc).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

# Projetos compose legados a remover. Adicione novos nomes aqui se surgirem.
LEGACY_PROJECTS=("jetsonstudy")

if ! has docker; then
  warn "docker não encontrado — nada a limpar."
  exit 0
fi

for proj in "${LEGACY_PROJECTS[@]}"; do
  ids=$(docker ps -aq --filter "label=com.docker.compose.project=${proj}" 2>/dev/null || true)
  if [ -z "${ids}" ]; then
    ok "stack legado '${proj}' já ausente."
    continue
  fi
  log "Removendo stack legado '${proj}' (containers em disputa pela câmera)..."
  # down derruba containers + rede do projeto; se faltar o compose file, cai no rm -f por label.
  wd=$(docker inspect "$(echo "${ids}" | head -n1)" \
        --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || true)
  if [ -n "${wd}" ] && [ -f "${wd}/docker-compose.yml" ]; then
    (cd "${wd}" && docker compose -p "${proj}" down --remove-orphans) || true
  fi
  # Garante remoção mesmo sem compose file.
  ids=$(docker ps -aq --filter "label=com.docker.compose.project=${proj}" 2>/dev/null || true)
  if [ -n "${ids}" ]; then
    # shellcheck disable=SC2086
    docker rm -f ${ids} || true
  fi
  ok "stack legado '${proj}' removido."
done
