#!/usr/bin/env bash
# 40-docker.sh — instala Docker Engine e habilita o serviço. Idempotente.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_root

if has docker; then
  ok "Docker já instalado: $(docker --version)"
else
  log "Instalando Docker via script oficial (suporta arm64/Jetson)..."
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh
fi

systemctl enable --now docker

# Permite ao usuário real rodar docker sem sudo.
u="$(real_user)"
if [ "$u" != "root" ] && ! id -nG "$u" | grep -qw docker; then
  usermod -aG docker "$u"
  warn "Usuário '${u}' adicionado ao grupo docker. Faça logout/login (ou 'newgrp docker')."
fi

ok "Docker pronto."
