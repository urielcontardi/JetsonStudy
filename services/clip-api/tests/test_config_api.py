import yaml
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def config_file(tmp_path):
    cfg = {
        "conveyor": {
            "enabled": True,
            "periodic_upload_enabled": True,
            "periodic_upload_interval_s": 600,
        }
    }
    p = tmp_path / "orwell.yaml"
    p.write_text(yaml.dump(cfg))
    return p


@pytest.fixture
def client(config_file, monkeypatch):
    monkeypatch.setenv("ORWELL_INDEX_DB", str(config_file.parent / "idx.sqlite"))
    monkeypatch.setenv("ORWELL_CONFIG", str(config_file))
    from clip_api.main import create_app
    return TestClient(create_app())


def test_get_config_returns_periodic_fields(client):
    r = client.get("/config")
    assert r.status_code == 200
    data = r.json()
    assert data["periodic_upload_enabled"] is True
    assert data["periodic_upload_interval_s"] == 600


def test_patch_config_updates_interval(client, config_file):
    r = client.patch("/config", json={"periodic_upload_interval_s": 300})
    assert r.status_code == 200
    assert r.json()["periodic_upload_interval_s"] == 300

    raw = yaml.safe_load(config_file.read_text())
    assert raw["conveyor"]["periodic_upload_interval_s"] == 300


def test_patch_config_rejects_invalid_interval(client):
    r = client.patch("/config", json={"periodic_upload_interval_s": 30})
    assert r.status_code == 422


def test_get_upload_stats_empty(client):
    r = client.get("/upload-stats")
    assert r.status_code == 200
    data = r.json()
    assert data["pending"] == 0
    assert data["failed"] == 0
    assert data["last_uploaded_at"] is None
