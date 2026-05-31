# ADR-0006 — Gravação em segmentos fMP4/CMAF + playlist HLS (não SVO)

**Status:** Aceito · 2026-05-31 (revisado para CMAF/HLS)

## Contexto
O buffer circular precisa de gravação contínua em pedaços com rotação, consumo eficiente
(extração de clipe e "GET intervalo") e, idealmente, streaming. Opções de formato: MP4 simples
segmentado, **fMP4/CMAF** (MP4 fragmentado, base de HLS/DASH), **MPEG-TS** (HLS clássico) ou **SVO**
(proprietário Stereolabs). Estado da arte de DVR/NVR (cloud DVR, time-shift, Frigate) usa
**segmentos curtos + índice**, e o formato moderno é **CMAF/fMP4** (uma cópia serve HLS e DASH,
byte-range, concatenação limpa, streaming no navegador).

## Decisão
- **Gravação contínua em segmentos curtos**, formato **fMP4/CMAF**, com **playlist HLS (.m3u8)**
  por câmera (streaming via Tailscale "de graça"; segmentos também tocam como arquivo).
- **Duração do segmento: ~4s por padrão**, **configurável** (`config/`) — fácil de mudar para
  2s/6s/10s sem mexer em código.
- **GOP ~1s** (keyframe a cada ~segundo): a **precisão do corte** vem do GOP, não do tamanho do
  segmento. Cortes por **cópia de stream** (ffmpeg `-c copy`), gerando MP4 *faststart* standalone
  para clipes (GET e evento).
- Em GStreamer/DeepStream: `hlssink2` (emite segmentos + playlist) ou `splitmuxsink` com muxer
  fragmentado.
- **Não** usar SVO (proprietário, exige exportação, lock-in).

## Consequências
- Arquivos pequenos → rotação granular, seek rápido, clipe barato, upload paralelo, corrupção
  isolada. Custo: mais arquivos/índice → mitigado por layout `data/cam/AAAA/MM/DD/HH/` e segmento
  de ~4s (não excessivamente pequeno).
- Streaming HLS habilitado sem trabalho extra significativo (bônus para futura UI de playback).
- Duração do segmento deve ser **múltiplo do GOP** (segmentos contêm GOPs inteiros).
- Init segment (fMP4) por câmera/parâmetros + segmentos `.m4s`.
- Índice em **SQLite** (ADR-0007) mapeia tempo → segmento; playlist `.m3u8` é redundância útil
  para players.
