# ADR-0014 — Encoder selecionável por config (NVENC HW default + x264 SW fallback)

**Status:** Aceito · 2026-06-01 · Supersede [ADR-0005](0005-encode-h264-software-perfil-reduzido.md)

## Contexto
O hardware-alvo do projeto passou a ser a **Jetson Orin NX**, que **possui NVENC** (encoder de
hardware), ao contrário da Orin Nano (ADR-0005). O software deve permanecer **agnóstico ao
módulo** (ADR-0012).

## Decisão
- **Encoder escolhido por configuração** (`capture.codec` + `capture.encoder`):
  - `hw` → `nvv4l2h265enc`/`nvv4l2h264enc` (NVENC); frames seguem em **NVMM** (sem cópia p/ CPU).
  - `sw` → `nvvidconv` + `x264enc` (libx264) como **fallback** (Nano / sem NVENC).
- **Default:** `h265`/`hw`, 1080p@30 (tunável; validar on-device).
- `h265` + `sw` é **rejeitado** na carga da config (inviável em tempo real).

## Consequências
- H.265 por HW vira viável → arquivos ~2× menores, mais retenção; CPU livre para a IA.
- A lógica de seleção vive em `recorder/pipeline.py` (`encoder_chain`), 100% testável.
- ⚠️ Bitrate: NVENC usa **bits/s** (`bitrate`), x264enc usa **kbit/s**. GOP: `iframeinterval`
  (HW) vs `key-int-max` (SW). Validar nomes/props exatos por JetPack/L4T on-device.
