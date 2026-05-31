# ADR-0008 — Acesso remoto via Tailscale

**Status:** Aceito · 2026-05-31

## Contexto
O device fica na borda (NAT/4G). É preciso acessar a Clip API e o console remotamente, com
segurança, sem expor portas. Alternativas: VPN tradicional, port-forwarding, ou a nuvem da
Stereolabs (ZED Hub, com lock-in).

## Decisão
**Tailscale** (VPN ponto-a-ponto sobre WireGuard) no host. Clip API e SSH alcançáveis pelo
**tailnet** (MagicDNS + ACLs + Tailscale SSH).

## Consequências
- **Sem portas abertas** (conexão de dentro para fora).
- Cada device vira um nome (`orwell-01`); ACLs controlam acesso.
- Complementar ao Rancher (que cuida da **gestão/atualização**, eixo diferente).
- Sem lock-in da nuvem da Stereolabs.
