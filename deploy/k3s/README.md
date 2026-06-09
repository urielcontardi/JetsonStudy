# K3s migration mapping

The Compose gateway exposes one same-origin HTTP contract:

- `/` -> dashboard
- `/api/*` -> clip-api, stripping `/api`
- `/preview/*` -> MediaMTX HLS, stripping `/preview`

K3s should preserve this contract with Traefik. Apply `strip-prefix.yaml`, create the Services
based on `services.example.yaml`, and use the routes from `ingress-route.example.yaml`.

Workload placement:

- `recorder`: Jetson node only, NVIDIA runtime, camera devices, `/dev/shm`, data/events HostPaths.
- `uploader`: Jetson node, no external Service.
- `clip-api`: container `8080`; ClusterIP Service `80` -> targetPort `8080`.
- `dashboard`: container `8080`; ClusterIP Service `80` -> targetPort `8080`.
- `preview`: MediaMTX HLS `8888`; ClusterIP Service `80` -> targetPort `8888`.
- `gateway`: removed after migration; Traefik becomes the HTTP edge.

The browser continues using `/api` and `/preview`; no frontend rebuild is needed.

Use the existing `/healthz` endpoints as Kubernetes readiness/liveness probes. Keep clip-api,
dashboard and preview as ClusterIP Services; only Traefik should expose HTTP outside the cluster.
Use Traefik `web` (`80`) initially and `websecure` (`443`) with a certificate for production.
