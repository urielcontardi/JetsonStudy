from fastapi.testclient import TestClient

from dashboard.main import create_app


def test_dashboard_uses_same_origin_routes():
    response = TestClient(create_app()).get("/")

    assert response.status_code == 200
    assert 'const CLIP_API = "/api";' in response.text
    assert 'const PREVIEW_BASE = "/preview";' in response.text
    assert "10.8.64.33" not in response.text


def test_dashboard_healthz():
    response = TestClient(create_app()).get("/healthz")
    assert response.json() == {"status": "ok"}


def test_dashboard_docs_alias_and_complete_api_catalog():
    response = TestClient(create_app()).get("/docs")

    assert response.status_code == 200
    assert "Referência da API" in response.text
    assert "/orwell/events/{sensor_id}" in response.text
    assert "/orwell/clip/{sensor_id}/{event_id}" in response.text
    assert "/events/{event_id}/clip" in response.text
    assert "/upload-stats" in response.text


def test_dashboard_serves_versioned_architecture_assets():
    client = TestClient(create_app())

    source = client.get("/architecture.d2")
    diagram = client.get("/architecture.svg")

    assert source.status_code == 200
    assert source.headers["content-type"].startswith("text/plain")
    assert 'gateway: "🐳 gateway  :80 público' in source.text
    assert diagram.status_code == 200
    assert diagram.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in diagram.content[:200]
