#!/usr/bin/env bash
# 85-conveyor-register.sh — imprime o extId do dispositivo para registro no Conveyor.
#
# O extId é derivado deterministicamente do eMMC CID (único por placa):
#   ext_id = blake3(bytes.fromhex(cid)).hexdigest()
#
# Uso (no Jetson):
#   sudo ./deploy/85-conveyor-register.sh
#
# Saída:
#   ext_id: <64-char hex>
#
# Após obter o ext_id:
#   1. Cadastrar esse extId no Conveyor (time de backend)
#   2. Setar conveyor.enabled: true no orwell.yaml (ou ORWELL_CONVEYOR__ENABLED=true)
#   3. O recorder auto-deriva o ext_id no boot — não precisa colocar no yaml.
#
# Idempotente: pode ser rodado quantas vezes quiser; sempre imprime o mesmo valor.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

SERIAL_PATH="/proc/device-tree/serial-number"
EMMC_PATH="/sys/block/mmcblk0/device/cid"

if ! command -v python3 &>/dev/null; then
  err "python3 não encontrado. Rode 10-base.sh antes."
  exit 1
fi

if [[ ! -f "${SERIAL_PATH}" ]] && [[ ! -f "${EMMC_PATH}" ]]; then
  err "Identificador de hardware não encontrado."
  err "  Jetson NX/NVMe : ${SERIAL_PATH}"
  err "  Jetson eMMC    : ${EMMC_PATH}"
  exit 1
fi

EXT_ID=$(python3 - <<PYEOF
import sys, os
try:
    from blake3 import blake3
except ImportError:
    sys.exit("blake3 não instalado. Rode: pip3 install blake3")

from pathlib import Path

serial_path = "${SERIAL_PATH}"
cid_path    = "${EMMC_PATH}"

try:
    serial = Path(serial_path).read_bytes().rstrip(b"\x00\n ").decode()
    print(blake3(serial.encode()).hexdigest())
    sys.exit(0)
except FileNotFoundError:
    pass

try:
    cid = Path(cid_path).read_text().strip()
    print(blake3(bytes.fromhex(cid)).hexdigest())
    sys.exit(0)
except FileNotFoundError:
    pass

sys.exit("nenhum identificador disponível")
PYEOF
)

HWID=$( [[ -f "${SERIAL_PATH}" ]] && cat "${SERIAL_PATH}" | tr -d '\0\n ' || cat "${EMMC_PATH}" | tr -d '[:space:]' )
log "hw id    : ${HWID}"
log "ext_id   : ${EXT_ID}"
echo ""
echo "============================================================"
echo "  CADASTRE ESTE extId NO CONVEYOR (time de backend):"
echo ""
echo "  ext_id: ${EXT_ID}"
echo ""
echo "  Depois: conveyor.enabled: true no orwell.yaml"
echo "  O recorder deriva o ext_id automaticamente no boot."
echo "============================================================"

# Grava em /etc/orwell/device-id para referência futura sem precisar do Python.
mkdir -p /etc/orwell
echo "${EXT_ID}" > /etc/orwell/device-id
log "ext_id salvo em /etc/orwell/device-id"
