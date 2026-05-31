# ADR-0001 — Gravar DVR de borda no Jetson com ZED X One S

**Status:** Aceito · 2026-05-31

## Contexto
Produto novo: gravação contínua de câmeras (estilo DVR) na borda, com recorte de intervalos sob
demanda e, futuramente, IA local que dispara envio de ~10 s de evento para a nuvem. Hardware
definido: Jetson Orin Nano + carrier/ZED Box (GMSL2) + 2× ZED X One S + NVMe. Acesso remoto por
Tailscale; futura frota com Rancher.

## Decisão
Construir Orwell como um conjunto de **serviços conteinerizados** na borda: gravação contínua em
buffer circular (segmentos rotativos), API de recorte, e ganchos para IA/nuvem. POC rápida, com
fronteiras prontas para escalar.

## Consequências
- Foco inicial em **gravação + recorte** (valor imediato), IA como fase 2.
- Decisões subsequentes (ADR-0002…0012) detalham stack, encode, deploy e escala.
