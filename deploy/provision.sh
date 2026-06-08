#!/usr/bin/env bash
# provision.sh — provisiona uma nova placa Orwell no Tailscale.
#
# Uso:
#   OMNI_REGISTER_TOKEN=<token> ./deploy/provision.sh <IP_LOCAL_DA_JETSON>
#
# O que faz (tudo automático):
#   1. SSH na placa → lê o MAC da Ethernet (device_id)
#   2. Chama register-api → obtém auth_key + hostname
#   3. SSH na placa → conecta ao Tailscale
#
# Pré-requisitos:
#   - Esta máquina no Tailscale (para alcançar o register-api)
#   - sshpass instalado:  brew install sshpass
#   - OMNI_REGISTER_TOKEN definido (NÃO comitar o token)
#
# Variáveis opcionais:
#   OMNI_REGISTER_API   — default: http://omnicluster-ctrl-dev-ashburn-01:30443
#   OMNI_PRODUCT        — default: omnitrac
#   SSH_USER            — default: user
#   SSH_PASS            — default: admin

set -euo pipefail

JETSON_IP="${1:?Uso: $0 <IP_LOCAL_DA_JETSON>}"
SSH_USER="${SSH_USER:-user}"
SSH_PASS="${SSH_PASS:-admin}"
REGISTER_API="${OMNI_REGISTER_API:-http://omnicluster-ctrl-dev-ashburn-01:30443}"
REGISTER_TOKEN="${OMNI_REGISTER_TOKEN:?Defina OMNI_REGISTER_TOKEN=<token>}"
PRODUCT="${OMNI_PRODUCT:-omnitrac}"

# ── helpers ───────────────────────────────────────────────────────────────────
log() { echo "  [$(date +%H:%M:%S)] $*"; }
ok()  { echo "  ✓ $*"; }
err() { echo "  ✗ $*" >&2; exit 1; }

_ssh() { sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
           "$SSH_USER@$JETSON_IP" "$@"; }

# ── pré-requisitos ────────────────────────────────────────────────────────────
command -v sshpass >/dev/null 2>&1 || err "sshpass não encontrado — instale: brew install sshpass"
command -v curl    >/dev/null 2>&1 || err "curl não encontrado."
command -v python3 >/dev/null 2>&1 || err "python3 não encontrado."

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Orwell Provisioning"
echo "  Jetson : $JETSON_IP"
echo "  API    : $REGISTER_API"
echo "═══════════════════════════════════════════════════"

# ── 1. Verifica se Tailscale já está conectado ────────────────────────────────
log "Verificando Tailscale na placa..."
TS_STATE=$(_ssh \
  'tailscale status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get(\"BackendState\",\"unknown\"))" 2>/dev/null || echo "unknown"')

if [[ "$TS_STATE" == "Running" ]]; then
  TS_IP=$(_ssh 'tailscale ip -4 2>/dev/null | head -1 || echo "?"')
  ok "Tailscale já conectado — IP: $TS_IP"
  echo ""
  exit 0
fi

# ── 2. Lê o device_id (MAC da Ethernet) ──────────────────────────────────────
log "Lendo device_id da placa..."
DEVICE_ID=$(_ssh '
  for iface in /sys/class/net/en* /sys/class/net/eth*; do
    [ -f "$iface/address" ] || continue
    mac=$(cat "$iface/address" | tr -d ":" | tr "[:upper:]" "[:lower:]")
    [ "$mac" = "000000000000" ] && continue
    echo "$mac" && exit 0
  done
  exit 1
') || err "Não foi possível ler o MAC da placa (interface en* ou eth*)."
ok "device_id : $DEVICE_ID"

# ── 3. Chama register-api ─────────────────────────────────────────────────────
log "Chamando register-api..."
RESPONSE=$(curl -sf \
  -X POST "${REGISTER_API}/tailscale-key" \
  -H "Authorization: Bearer ${REGISTER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"device_id\":\"${DEVICE_ID}\", \"product\":\"${PRODUCT}\"}" \
) || err "Falha ao chamar o register-api. Você está no Tailscale?"

TS_AUTHKEY=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['auth_key'])")
TS_HOSTNAME=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['hostname'])")

ok "hostname  : $TS_HOSTNAME"
ok "auth_key  : ${TS_AUTHKEY:0:32}..."

# ── 4. Conecta Tailscale na placa ─────────────────────────────────────────────
log "Conectando Tailscale na placa..."
_ssh "echo '${SSH_PASS}' | sudo -S tailscale up \
  --auth-key='${TS_AUTHKEY}' \
  --hostname='${TS_HOSTNAME}' \
  --ssh 2>&1 | grep -v '^$' || true"

TS_IP=$(_ssh 'tailscale ip -4 2>/dev/null | head -1 || echo "?"')

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Pronto!"
echo "  hostname : $TS_HOSTNAME"
echo "  IP       : $TS_IP"
echo "  Acesso   : ssh user@$TS_HOSTNAME"
echo "═══════════════════════════════════════════════════"
echo ""
