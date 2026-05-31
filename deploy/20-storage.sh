#!/usr/bin/env bash
# 20-storage.sh — prepara o armazenamento dos segmentos de vídeo. Idempotente.
#
# PADRÃO (STORAGE_MODE="dir"): cria DATA_DIR no disco existente. NÃO formata nada.
# OPCIONAL (STORAGE_MODE="disk"): formata e monta um NVMe DEDICADO e SEPARADO.
#   ⚠️ DESTRUTIVO. Confirme MUITO bem o device — NUNCA aponte para o disco de boot.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_root
require_var DATA_DIR

case "${STORAGE_MODE:-dir}" in
  dir)
    log "STORAGE_MODE=dir — usando diretório no disco existente: ${DATA_DIR}"
    mkdir -p "${DATA_DIR}"
    chown -R "$(real_user)":"$(real_user)" "${DATA_DIR}" || true
    avail=$(df -h --output=avail "${DATA_DIR}" | tail -1 | tr -d ' ')
    ok "Diretório de dados pronto (${DATA_DIR}, livre: ${avail})."
    ;;

  disk)
    require_var DEDICATED_NVME_DEVICE
    dev="${DEDICATED_NVME_DEVICE}"
    log "STORAGE_MODE=disk — alvo: ${dev} (DEDICADO)"

    # Trava de segurança: recusa se for o device de boot/raiz.
    root_src=$(findmnt -no SOURCE / || true)
    if [[ "$root_src" == "$dev"* ]]; then
      err "ABORTADO: ${dev} parece ser o disco de boot/raiz (${root_src}). Nunca formate o disco de boot."
      exit 1
    fi
    if [ ! -b "$dev" ]; then
      err "Device de bloco não encontrado: ${dev}"
      exit 1
    fi

    # Idempotência: só formata se ainda não tiver filesystem.
    if blkid "$dev" >/dev/null 2>&1; then
      warn "${dev} já possui filesystem — não vou reformatar."
    else
      warn "Formatando ${dev} como ${DEDICATED_NVME_FS} (DESTRUTIVO). Ctrl-C em 10s para abortar..."
      sleep 10
      mkfs."${DEDICATED_NVME_FS}" "$dev"
    fi

    mkdir -p "${DATA_DIR}"
    uuid=$(blkid -s UUID -o value "$dev")
    if ! grep -q "$uuid" /etc/fstab; then
      echo "UUID=${uuid} ${DATA_DIR} ${DEDICATED_NVME_FS} defaults,noatime 0 2" >>/etc/fstab
      ok "Entrada adicionada ao /etc/fstab."
    fi
    mount -a
    chown -R "$(real_user)":"$(real_user)" "${DATA_DIR}" || true
    ok "NVMe dedicado montado em ${DATA_DIR}."
    ;;

  *)
    err "STORAGE_MODE inválido: '${STORAGE_MODE}'. Use 'dir' ou 'disk'."
    exit 1
    ;;
esac
