#!/usr/bin/env bash
# 30-gmsl-driver.sh — instala o driver GMSL da Stereolabs (kernel). Idempotente.
# ⚠️ Exige REBOOT após instalar. Casar o .deb com a versão L4T da placa.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_root

# Mostra a versão L4T para ajudar a escolher o .deb certo.
if [ -f /etc/nv_tegra_release ]; then
  log "Versão L4T detectada:"; cat /etc/nv_tegra_release
else
  warn "/etc/nv_tegra_release não encontrado — esta placa tem JetPack/L4T? Veja deploy/README.md."
fi

# Dependência conhecida do pacote da Stereolabs.
apt-get install -y libqt5core5a || true

ARTIFACT_DIR="${DEPLOY_DIR}/artifacts"
mkdir -p "${ARTIFACT_DIR}"
deb_path=""

if [ -n "${GMSL_DRIVER_DEB:-}" ] && [ -f "${ARTIFACT_DIR}/${GMSL_DRIVER_DEB}" ]; then
  deb_path="${ARTIFACT_DIR}/${GMSL_DRIVER_DEB}"
elif [ -n "${GMSL_DRIVER_URL:-}" ]; then
  fname="$(basename "${GMSL_DRIVER_URL}")"
  log "Baixando driver GMSL de ${GMSL_DRIVER_URL} ..."
  curl -fsSL "${GMSL_DRIVER_URL}" -o "${ARTIFACT_DIR}/${fname}"
  deb_path="${ARTIFACT_DIR}/${fname}"
else
  err "Driver GMSL não configurado."
  err "Defina GMSL_DRIVER_DEB (arquivo em deploy/artifacts/) ou GMSL_DRIVER_URL em 00-versions.env."
  err "Baixe o .deb correto (casando placa + deserializer + L4T) em:"
  err "  https://www.stereolabs.com/developers/drivers"
  exit 1
fi

log "Instalando ${deb_path} ..."
dpkg -i "${deb_path}" || apt-get install -f -y

ok "Driver GMSL instalado. ⚠️ REINICIE a placa antes de usar as câmeras (sudo reboot)."
touch /var/lib/orwell/.gmsl-needs-reboot 2>/dev/null || true
