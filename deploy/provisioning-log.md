# Log de provisionamento (notas por placa)

Registre aqui **desvios manuais**, valores reais usados e particularidades por device/lote.
O comportamento padrão já é capturado pelos scripts; este arquivo é para o que foge deles.

> Regra: se você precisou rodar algo no host que **não** estava num script, ou (a) adicione ao
> script apropriado, ou (b) registre aqui e abra um item para automatizar depois.

---

## Template (copie por placa)

### Device: `orwell-XX`
- **Data:** YYYY-MM-DD
- **JetPack/L4T:** (saída de `cat /etc/nv_tegra_release`)
- **Driver GMSL usado:** (nome do .deb)
- **Storage:** modo (`dir`/`disk`), caminho, tamanho do NVMe
- **Tailscale:** hostname, conectado? (sim/não)
- **Desvios manuais:** (qualquer comando rodado fora dos scripts — e por quê)
- **Pendências de automação:** (o que registrar/automatizar depois)

---

## Pendências de validação on-device (reescrita Orin NX — 2026-06-01)

Itens que só podem ser verificados no Jetson (dev foi em macOS). Validar e marcar aqui:

- [ ] Nomes/props exatos de `nvv4l2h265enc`/`nvv4l2h264enc` no JetPack/L4T/DeepStream do device
      (`bitrate` em bits/s, `iframeinterval`). Ajustar `recorder/pipeline.py:encoder_chain` se preciso.
- [ ] `rtspclientsink` disponível na imagem DeepStream (preview). Se faltar, instalar
      `gstreamer1.0-plugins-{good,bad}` no Dockerfile do recorder.
- [ ] `recorder` em PLAYING com `codec=h265/encoder=hw`: `docker compose --profile jetson up -d --build recorder`
      e conferir segmentos surgindo em `data/` + `docker compose logs -f recorder`.
- [ ] Concat fMP4 **H.265** pela Clip API (`ffmpeg -c copy`) → MP4 tocável.
- [ ] Tag correta da imagem DeepStream no `services/recorder/Dockerfile` (ARG `DEEPSTREAM_IMAGE`)
      casando o JetPack instalado.
- [ ] Preview ao vivo: `preview.enabled: true` + `docker compose --profile dev up -d preview` →
      abrir `rtsp://orwell-nx:8554/cam0` (VLC) e `http://orwell-nx:8889/cam0` (WebRTC) do Mac.

---
<!-- adicione entradas reais abaixo -->
