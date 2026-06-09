# Orwell API — Referência curl

Base URL: `http://orwell-4cbb47c1331a/api`

> Todos os timestamps são em **UTC** (sufixo `Z`). Brasília = UTC-3, portanto 18:00 BRT = 21:00Z.

---

## Status

```bash
curl http://orwell-4cbb47c1331a/api/healthz
# {"status":"ok"}
```

---

## Listar câmeras disponíveis

```bash
curl http://orwell-4cbb47c1331a/api/cameras
# ["0"]
```

---

## Ver período gravado (range)

```bash
curl "http://orwell-4cbb47c1331a/api/range?camera=0"
# {"camera":"0","first":"2026-06-03T20:47:24Z","last":"2026-06-03T21:23:09Z"}
```

---

## Últimos N minutos

```bash
# últimos 1 minuto
END=$(curl -s "http://orwell-4cbb47c1331a/api/range?camera=0" | python3 -c "import sys,json; print(json.load(sys.stdin)['last'])")
START=$(python3 -c "from datetime import datetime,timedelta,timezone; t=datetime.fromisoformat('${END}'.replace('Z','+00:00')); print((t-timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
curl "http://orwell-4cbb47c1331a/api/clips?camera=0&start=${START}&end=${END}" -o ultimo_1min.mp4

# últimos 5 minutos
curl "http://orwell-4cbb47c1331a/api/clips?camera=0&start=${START_5MIN}&end=${END}" -o ultimo_5min.mp4
```

---

## Baixar clipe por intervalo

```bash
curl "http://orwell-4cbb47c1331a/api/clips?camera=0&start=2026-06-03T21:18:48Z&end=2026-06-03T21:19:48Z" \
  -o clipe.mp4
```

> Dica: use o dashboard em `http://orwell-4cbb47c1331a`.

---

## Listar segmentos de um intervalo

```bash
curl "http://orwell-4cbb47c1331a/api/segments?camera=0&start=2026-06-03T21:00:00Z&end=2026-06-03T21:10:00Z"
# ["/data/0/2026/06/03/21/seg-....m4s", ...]
```

---

## Conversão de horário BRT → UTC

| BRT (Brasília) | UTC |
|---|---|
| 18:00 | 21:00Z |
| 18:30 | 21:30Z |
| 00:00 | 03:00Z |

```bash
# converter hora local BRT para UTC (no terminal)
python3 -c "
from datetime import datetime, timezone, timedelta
brt = datetime(2026, 6, 3, 18, 0, 0, tzinfo=timezone(timedelta(hours=-3)))
print(brt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
"
# 2026-06-03T21:00:00Z
```
