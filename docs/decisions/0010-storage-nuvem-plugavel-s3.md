# ADR-0010 — Storage de nuvem plugável (S3 por padrão)

**Status:** Aceito · 2026-05-31 · *Implementação adiada para Fase 2*

## Contexto
Clipes de evento (~10 s) precisam ir para a nuvem, mas o provedor **ainda não está definido**.
O serviço de upload e o transporte de eventos são Fase 2 (sem MQTT/broker na Fase 1).

## Decisão
O serviço de upload (Fase 2) usará uma **interface de storage plugável** (`put(path, metadata) ->
uri`). Implementação **padrão: S3** (compatível com MinIO/R2). Azure/GCP entram como
implementações adicionais quando a nuvem for escolhida.

## Consequências
- Não trava a decisão de nuvem; troca de provedor = nova implementação da interface.
- Sem lock-in; testável localmente com MinIO.
- Credenciais via env/secret (12-factor).
