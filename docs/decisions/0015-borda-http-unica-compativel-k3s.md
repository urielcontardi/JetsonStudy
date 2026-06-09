# ADR-0015 — Borda HTTP única compatível com K3s

**Status:** Aceito · 2026-06-09

## Contexto

Dashboard, Clip API e HLS eram expostos em portas diferentes. O frontend precisava conhecer IP ou
hostname do device e isso falhava ao alternar entre LAN e Tailscale. No K3s, o padrão é uma borda
HTTP única via Ingress.

## Decisão

- Expor uma única origem HTTP na porta padrão `80` no Compose.
- Usar `/` para dashboard, `/api` para Clip API e `/preview` para HLS.
- Manter dashboard, Clip API e HLS sem portas HTTP publicadas diretamente.
- Padronizar os apps HTTP internos em `8080`; manter `8888` no MediaMTX por ser sua porta HLS.
- Usar Nginx no Compose e substituir apenas essa borda por Traefik Ingress no K3s.
- No K3s, expor cada ClusterIP Service em `80` com `targetPort` explícito.
- Manter RTSP (`8554`) e WebRTC (`8889` + UDP) separados por exigirem transporte próprio.

## Consequências

- LAN e Tailscale usam a mesma URL relativa, sem CORS ou configuração de IP no frontend.
- O frontend não muda durante a migração para K3s.
- Healthchecks do Compose mapeiam diretamente para readiness/liveness probes.
- A exposição externa fica concentrada em um único componente.
- HTTPS usa a porta padrão `443` quando certificados forem configurados no Traefik.
