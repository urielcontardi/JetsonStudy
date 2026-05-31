# ADR-0012 — Orin NX como caminho de escala (NVENC/H.265)

**Status:** Aceito (planejado) · 2026-05-31

## Contexto
O Orin Nano não tem NVENC (ADR-0005), limitando encode a software e disputando CPU com a IA. O
módulo **Orin NX** é **pino-compatível** com o mesmo carrier/devkit e **possui NVENC**.

## Decisão
Adotar o **Orin NX** como **caminho de escala de hardware** quando o orçamento de encode/IA
apertar — **trocando apenas o módulo**, sem reprojetar a placa.

## Consequências
- Destrava **H.265 por hardware**, libera CPU para inferência, permite mais câmeras por device.
- Software deve permanecer **agnóstico ao módulo** (perfil/codec configuráveis) para que a troca
  seja só de hardware + ajuste de config.
- Decisão de **quando** trocar depende da validação empírica de CPU na POC (Fase 1/2).
