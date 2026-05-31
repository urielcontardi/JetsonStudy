# ADR-0005 — Encode H.264 por software + perfil reduzido

**Status:** Aceito · 2026-05-31

## Contexto
O **Jetson Orin Nano não tem NVENC** (encoder de hardware) — confirmado pela NVIDIA ("Software
Encode in Orin Nano"). Só há **NVDEC** (decode). Encode precisa ser por **software (CPU)**.
H.265 software em tempo real para 2 streams é inviável. Há ainda o roadmap de IA, que disputa CPU.

## Decisão
- **Codec:** **H.264 por software** (`x264enc`/libx264), preset rápido, **GOP ~1 s**.
- **Perfil POC reduzido:** **1080p @ 15 fps**, 2 câmeras (sensor nativo é 1200p@30). **Tunável**.

## Consequências
- Viável no Orin Nano deixando CPU para a inferência; arquivos maiores que H.265.
- **GOP curto** habilita recorte por **cópia de stream** (sem recomprimir) — barato.
- Validar **orçamento de CPU** on-device (encode + futura inferência).
- Para H.265/hardware e mais carga: caminho **Orin NX** (ADR-0012).
