# ADR-0011 — Sem Yocto na POC

**Status:** Aceito · 2026-05-31

## Contexto
Yocto permite montar uma distribuição Linux sob medida (imagem mínima, read-only, OTA) — ótimo
para produto em escala, mas com **alto custo de setup/manutenção**. A pergunta era se já valia a
pena.

## Decisão
**Não usar Yocto na POC.** Usar **JetPack padrão** + Docker. Reavaliar Yocto (ou Rancher Elemental)
na fase de **industrialização/frota**.

## Consequências
- POC sai muito mais rápido; ambiente de dev = ambiente de produção (mesmo JetPack).
- Atualização de **SO/driver** continua manual na POC (provisionamento em `deploy/`).
- A camada de OTA de SO entra junto com a frota (ADR-0009 / operations.md).
