from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_nginx_gateway_preserves_public_route_contract():
    config = (ROOT / "services/gateway/nginx.conf").read_text()

    assert "location /api/" in config
    assert "proxy_pass http://clip-api:8080/" in config
    assert "location /preview/" in config
    assert "proxy_pass http://preview:8888/" in config
    assert "proxy_pass http://dashboard:8080" in config


def test_k3s_example_preserves_compose_route_contract():
    route_docs = list(
        yaml.safe_load_all(
            (ROOT / "deploy/k3s/ingress-route.example.yaml").read_text()
        )
    )
    middleware_docs = list(
        yaml.safe_load_all(
            (ROOT / "deploy/k3s/strip-prefix.yaml").read_text()
        )
    )

    matches = [route["match"] for route in route_docs[0]["spec"]["routes"]]
    service_ports = [
        route["services"][0]["port"]
        for route in route_docs[0]["spec"]["routes"]
    ]
    prefixes = [
        prefix
        for document in middleware_docs
        for prefix in document["spec"]["stripPrefix"]["prefixes"]
    ]

    assert matches == [
        "PathPrefix(`/api`)",
        "PathPrefix(`/preview`)",
        "PathPrefix(`/`)",
    ]
    assert service_ports == [80, 80, 80]
    assert prefixes == ["/api", "/preview"]


def test_compose_publishes_http_only_through_gateway():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    assert services["gateway"]["ports"] == ["80:80"]
    assert services["clip-api"]["expose"] == ["8080"]
    assert services["dashboard"]["expose"] == ["8080"]
    assert "ports" not in services["clip-api"]
    assert "ports" not in services["dashboard"]


def test_k3s_http_services_have_standard_port_and_explicit_targets():
    service_docs = list(
        yaml.safe_load_all(
            (ROOT / "deploy/k3s/services.example.yaml").read_text()
        )
    )
    services = {
        document["metadata"]["name"]: document["spec"]["ports"][0]
        for document in service_docs
    }

    assert services == {
        "orwell-clip-api": {"name": "http", "port": 80, "targetPort": 8080},
        "orwell-dashboard": {"name": "http", "port": 80, "targetPort": 8080},
        "orwell-preview": {"name": "http-hls", "port": 80, "targetPort": 8888},
    }
