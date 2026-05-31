# ADR-0004 — Stack: tudo em Python

**Status:** Aceito · 2026-05-31

## Contexto
Cogitou-se separar plano de mídia (DeepStream, C++/Python) do plano de controle (Go). Mas
**DeepStream não tem binding Go** (só C++ e Python/`pyds`). A dúvida central era: *"dá para fazer
tudo em Python sem perder performance?"*

## Decisão
**Tudo em Python.** App DeepStream com **`pyds`**; Clip API e Uploader com **FastAPI/Python**.

## Justificativa (performance)
O trabalho pesado (captura, encode, inferência) roda na **camada nativa C/CUDA** do
GStreamer/DeepStream/TensorRT; os **frames vivem na GPU** e não passam pelo Python. O Python só
**monta o pipeline** e **reage a eventos** (metadados leves). Logo, **não há perda de performance**
— desde que **não** se processe cada pixel de cada frame em Python (ex.: numpy por frame).

## Consequências
- Uma única linguagem → POC mais simples e rápida; menos atrito de manutenção.
- Regra de ouro registrada no CLAUDE.md: nunca puxar pixels por frame para o Python.
- Go descartado (era opcional).
