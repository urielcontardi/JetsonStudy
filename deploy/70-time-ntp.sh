#!/usr/bin/env bash
# 70-time-ntp.sh — tempo confiável (UTC + NTP). Idempotente.
# O índice e os recortes de vídeo dependem de relógio sincronizado.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_root

tz="${TIMEZONE:-UTC}"
log "Definindo timezone=${tz} e habilitando NTP..."
timedatectl set-timezone "${tz}"
timedatectl set-ntp true

# Garante o serviço de sincronização ativo.
systemctl enable --now systemd-timesyncd 2>/dev/null || true

sleep 2
log "Status do relógio:"
timedatectl show -p Timezone -p NTP -p NTPSynchronized 2>/dev/null || timedatectl status | head -5
ok "Tempo configurado."
