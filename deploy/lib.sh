#!/usr/bin/env bash
# lib.sh — helpers comuns para os scripts de provisionamento. Sourceado pelos demais.
set -euo pipefail

# Diretório deste script (deploy/)
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Carrega as variáveis de versão/config (se existir).
if [ -f "${DEPLOY_DIR}/00-versions.env" ]; then
  # shellcheck disable=SC1091
  source "${DEPLOY_DIR}/00-versions.env"
fi

# Log de provisionamento (registro do que foi executado neste host).
PROV_LOG="${PROV_LOG:-/var/log/orwell-provisioning.log}"

_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

log()  { echo -e "[\033[0;36m$(_ts)\033[0m] $*"; _logfile "$*"; }
ok()   { echo -e "[\033[0;32m OK \033[0m] $*"; _logfile "OK: $*"; }
warn() { echo -e "[\033[0;33mWARN\033[0m] $*" >&2; _logfile "WARN: $*"; }
err()  { echo -e "[\033[0;31mERR \033[0m] $*" >&2; _logfile "ERR: $*"; }

_logfile() {
  # Best-effort: registra no arquivo de log se houver permissão.
  if [ -w "$(dirname "$PROV_LOG")" ] 2>/dev/null || [ -w "$PROV_LOG" ] 2>/dev/null; then
    echo "[$(_ts)] $*" >>"$PROV_LOG" 2>/dev/null || true
  fi
}

# Exige execução como root (via sudo).
require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    err "Rode como root:  sudo $0"
    exit 1
  fi
}

# Usuário real por trás do sudo (para adicionar ao grupo docker, etc.)
real_user() { echo "${SUDO_USER:-${USER:-root}}"; }

# Verifica se um comando existe.
has() { command -v "$1" >/dev/null 2>&1; }

# Exige uma variável não-vazia (senão aborta com mensagem).
require_var() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    err "Variável '${name}' não definida. Edite deploy/00-versions.env."
    exit 1
  fi
}
