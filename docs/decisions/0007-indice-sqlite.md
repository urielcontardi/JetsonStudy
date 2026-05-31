# ADR-0007 — Índice de segmentos em SQLite

**Status:** Aceito · 2026-05-31

## Contexto
A Clip API precisa mapear rapidamente `[start, end]` → arquivos de segmento. Opções: varrer o
diretório a cada request, um índice em arquivo (SQLite) ou um banco com servidor (Postgres).

## Decisão
**SQLite** (arquivo único, sem servidor) como índice: `segments(camera_id, t_inicio, t_fim, path,
size, created_at)`. Escrito pelo `recorder`, lido pela `clip-api`.

## Consequências
- Zero infra extra; perfeito para borda single-node.
- Consultas por intervalo simples e rápidas.
- Acesso concorrente leve (1 escritor, poucos leitores) — adequado; usar WAL se necessário.
- Se a frota exigir agregação central, dados podem ser sincronizados depois (não é requisito agora).
